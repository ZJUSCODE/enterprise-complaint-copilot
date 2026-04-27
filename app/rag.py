from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import chromadb
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import Settings, VECTOR_DIR
from app.utils import (
    estimate_cost_breakdown,
    estimate_text_tokens,
    extract_langchain_usage,
    lexical_overlap_score,
    summarize_text,
)


class PolicyKnowledgeBase:
    def __init__(self, path: Path):
        self.documents: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))

    def lexical_search(self, query: str, category: str | None = None, top_k: int = 3) -> list[dict[str, Any]]:
        query_lower = query.lower()
        scored: list[tuple[float, dict[str, Any]]] = []
        for doc in self.documents:
            score = 0.0
            if category and (doc["category"] == category or doc["category"] == "通用"):
                score += 4
            for keyword in doc.get("keywords", []):
                if keyword.lower() in query_lower:
                    score += 2
            if doc["category"] in query:
                score += 3
            doc_text = f"{doc['title']} {doc['excerpt']} {' '.join(doc.get('guidance', []))}"
            overlap = lexical_overlap_score(query, doc_text)
            score += overlap
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:top_k]]


class LangChainRAGService:
    def __init__(self, settings: Settings, knowledge_base: PolicyKnowledgeBase):
        self.settings = settings
        self.knowledge_base = knowledge_base
        self.available = False
        self.error: str | None = None
        self.client: chromadb.PersistentClient | None = None
        self.collection: Any | None = None
        self.embeddings: OpenAIEmbeddings | None = None
        self.llm: ChatOpenAI | None = None

        if not settings.use_langchain_rag or not settings.embedding_api_key or not settings.llm_api_key:
            self.error = "缺少 LLM 或 Embedding 配置，LangChain RAG 未启用。"
            return
        try:
            if not VECTOR_DIR.exists() and not settings.auto_build_vector_store:
                self.error = f"向量库目录不存在：{VECTOR_DIR.name}。请运行 scripts/build_openai_vector_store.py 构建；当前使用本地规则检索。"
                return
            self.embeddings = OpenAIEmbeddings(api_key=settings.embedding_api_key, base_url=settings.embedding_base_url, model=settings.embedding_model)
            self.client = chromadb.PersistentClient(path=str(VECTOR_DIR))
            self.collection = self.client.get_or_create_collection(name="policy_docs")
            existing = self.collection.get()
            if not existing["ids"]:
                if not settings.auto_build_vector_store:
                    self.error = "向量库为空。请运行 scripts/build_openai_vector_store.py 构建；当前使用本地规则检索。"
                    return
                texts = [f"{doc['title']}\n类别：{doc['category']}\n摘要：{doc['excerpt']}\n规则：{'；'.join(doc['guidance'])}" for doc in knowledge_base.documents]
                metadatas = [{"doc_id": doc["id"], "title": doc["title"], "category": doc["category"], "citation": doc["citation"]} for doc in knowledge_base.documents]
                ids = [doc["id"] for doc in knowledge_base.documents]
                vectors = self.embeddings.embed_documents(texts)
                self.collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=vectors)
            self.llm = ChatOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, model=settings.llm_model, temperature=0)
            self.available = True
        except Exception as exc:
            self.error = f"向量库初始化失败：{exc}。当前使用本地规则检索。"

    def query(self, question: str, category: str | None = None, top_k: int = 3) -> dict[str, Any]:
        start = time.perf_counter()
        if not self.available or not self.collection or not self.embeddings:
            retrieval_start = time.perf_counter()
            docs = self.knowledge_base.lexical_search(question, category=category, top_k=top_k)
            retrieval_ms = round((time.perf_counter() - retrieval_start) * 1000, 2)
            fallback_sources = []
            for rank, doc in enumerate(docs, start=1):
                fallback_sources.append({
                    "id": doc.get("id"),
                    "title": doc.get("title"),
                    "category": doc.get("category"),
                    "citation": doc.get("citation"),
                    "excerpt": doc.get("excerpt"),
                    "retrieval_score": round(1.0 - (rank - 1) * 0.1, 4),
                    "rerank_score": round(lexical_overlap_score(question, f"{doc.get('title', '')} {doc.get('excerpt', '')}"), 4),
                    "source": "lexical_fallback",
                })
            if docs:
                top_doc = docs[0]
                guidance = "；".join(top_doc.get("guidance", [])[:3])
                answer = f"基于 {top_doc['citation']}，建议先按以下口径处理：{guidance}"
            else:
                answer = "LangChain RAG 当前未启用，且本地规则检索未命中明确条款，建议转人工复核。"
            token_usage = {
                "embedding_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": estimate_text_tokens(answer),
                "total_tokens": estimate_text_tokens(answer),
            }
            return {
                "available": False,
                "answer": answer,
                "sources": fallback_sources,
                "fallback_reason": self.error or "未初始化",
                "retrieval_ms": retrieval_ms,
                "embedding_ms": 0,
                "generation_ms": 0,
                "total_ms": round((time.perf_counter() - start) * 1000, 2),
                "token_usage": token_usage,
                "cost_breakdown": estimate_cost_breakdown(self.settings, token_usage),
            }
        embedding_start = time.perf_counter()
        query_vector = self.embeddings.embed_query(question)
        embedding_ms = round((time.perf_counter() - embedding_start) * 1000, 2)
        retrieval_start = time.perf_counter()
        result = self.collection.query(query_embeddings=[query_vector], n_results=max(top_k * 2, 6))
        retrieval_ms = round((time.perf_counter() - retrieval_start) * 1000, 2)
        matched = []
        distances = result.get("distances", [[]])[0] if result.get("distances") else []
        for index, (metadata, document) in enumerate(zip(result.get("metadatas", [[]])[0], result.get("documents", [[]])[0])):
            distance = float(distances[index]) if index < len(distances) else 1.0
            retrieval_score = max(0.0, 1.0 - distance)
            matched.append({
                "id": metadata.get("doc_id"),
                "title": metadata.get("title"),
                "category": metadata.get("category"),
                "citation": metadata.get("citation"),
                "excerpt": summarize_text(document, limit=220),
                "retrieval_score": round(retrieval_score, 4),
                "rerank_score": round(lexical_overlap_score(question, f"{metadata.get('title', '')} {document}"), 4),
                "source": "vector_search",
            })
        matched = sorted(matched, key=lambda item: (item["rerank_score"], item["retrieval_score"]), reverse=True)[:top_k]
        context = "\n\n".join([f"[{item['citation']}] {item['title']} - {item['excerpt']}" for item in matched])
        prompt = "你是企业级售后 Copilot。请只基于给定上下文回答，不能编造规则。如果上下文不足，请明确说需要人工复核。\n\n" + f"问题：{question}\n\n上下文：\n{context}"
        generation_start = time.perf_counter()
        llm_usage = extract_langchain_usage(None, prompt=prompt, answer="")
        try:
            if self.llm:
                llm_message = self.llm.invoke(prompt)
                answer = llm_message.content
                llm_usage = extract_langchain_usage(llm_message, prompt=prompt, answer=answer)
            else:
                answer = "未配置语言模型。"
                llm_usage = extract_langchain_usage(None, prompt=prompt, answer=answer)
        except Exception as exc:
            answer = f"LangChain RAG 检索到了文档，但回答生成失败：{exc}"
            llm_usage = extract_langchain_usage(None, prompt=prompt, answer=answer)
        generation_ms = round((time.perf_counter() - generation_start) * 1000, 2)
        embedding_tokens = estimate_text_tokens(question)
        token_usage = {
            "embedding_tokens": embedding_tokens,
            "prompt_tokens": int(llm_usage.get("prompt_tokens", 0)),
            "completion_tokens": int(llm_usage.get("completion_tokens", 0)),
            "total_tokens": embedding_tokens + int(llm_usage.get("prompt_tokens", 0)) + int(llm_usage.get("completion_tokens", 0)),
        }
        return {
            "available": True,
            "answer": answer,
            "sources": matched,
            "retrieval_ms": retrieval_ms,
            "embedding_ms": embedding_ms,
            "generation_ms": generation_ms,
            "total_ms": round((time.perf_counter() - start) * 1000, 2),
            "token_usage": token_usage,
            "cost_breakdown": estimate_cost_breakdown(self.settings, token_usage),
        }
