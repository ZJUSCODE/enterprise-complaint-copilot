from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import chromadb
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI

from app.config import Settings, KB_DIR, VECTOR_DIR
from app.utils import (
    estimate_cost_breakdown,
    estimate_text_tokens,
    extract_usage,
    extract_langchain_usage,
    lexical_overlap_score,
    summarize_text,
)


VECTOR_MANIFEST = "kb_manifest.json"


def knowledge_base_hash(kb_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted([kb_dir / "policies.json", *kb_dir.glob("*.md")]):
        if not path.exists() or path.name.lower().startswith("readme"):
            continue
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _load_and_chunk_markdown_docs(kb_dir: Path) -> tuple[list[str], list[dict], list[str]]:
    """Load *.md files from kb_dir, split into chunks for vector indexing."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=300,
        chunk_overlap=50,
        separators=["\n## ", "\n\n", "\n", "。", "；", " "],
        keep_separator=True,
    )
    all_texts: list[str] = []
    all_metadatas: list[dict] = []
    all_ids: list[str] = []
    chunk_counter = 0

    for md_file in sorted(kb_dir.glob("*.md")):
        if md_file.name.lower().startswith("readme"):
            continue
        content = md_file.read_text(encoding="utf-8")
        chunks = splitter.split_text(content)
        if not chunks:
            continue
        name_lower = md_file.name.lower()
        first_heading = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        doc_title = first_heading.group(1).strip() if first_heading else md_file.stem
        category = "售后" if "after_sales" in name_lower else "物流" if "logistics" in name_lower else "生鲜" if "fresh" in name_lower else "通用"

        for chunk in chunks:
            chunk_counter += 1
            headings = re.findall(r"^##\s+(.+)$", chunk, re.MULTILINE)
            section_title = headings[-1].strip() if headings else ""
            chunk_id = f"{md_file.stem}_chunk_{chunk_counter:03d}"
            title = section_title or doc_title
            citation = f"{md_file.name} > {section_title}" if section_title else md_file.name
            all_texts.append(chunk)
            all_metadatas.append({
                "doc_id": chunk_id,
                "title": title,
                "category": category,
                "citation": citation,
                "source_file": md_file.name,
                "section_title": section_title,
            })
            all_ids.append(chunk_id)

    return all_texts, all_metadatas, all_ids


class PolicyKnowledgeBase:
    def __init__(self, path: Path):
        self.documents: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))

    def lexical_search(self, query: str, category: str | None = None, top_k: int = 3) -> list[dict[str, Any]]:
        query_lower = query.lower()
        scored: list[tuple[float, dict[str, Any]]] = []
        for doc in self.documents:
            if category and doc["category"] not in {category, "通用"}:
                continue
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
        self.generation_client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url) if settings.llm_api_key else None
        self.generation_available = self.generation_client is not None

        if not settings.use_langchain_rag or not settings.embedding_api_key or not settings.llm_api_key:
            self.error = "向量 Embedding 未启用；当前使用本地词法检索 + 大模型生成。"
            return
        try:
            if not VECTOR_DIR.exists() and not settings.auto_build_vector_store:
                self.error = f"向量库目录不存在：{VECTOR_DIR.name}。请运行 scripts/build_openai_vector_store.py 构建；当前使用本地规则检索。"
                return
            self.embeddings = OpenAIEmbeddings(api_key=settings.embedding_api_key, base_url=settings.embedding_base_url, model=settings.embedding_model)
            self.client = chromadb.PersistentClient(path=str(VECTOR_DIR))
            self.collection = self.client.get_or_create_collection(name="policy_docs")
            existing = self.collection.get()
            manifest_path = VECTOR_DIR / VECTOR_MANIFEST
            expected_hash = knowledge_base_hash(KB_DIR)
            manifest_hash = None
            if manifest_path.exists():
                try:
                    manifest_hash = json.loads(manifest_path.read_text(encoding="utf-8")).get("knowledge_base_hash")
                except (OSError, json.JSONDecodeError):
                    manifest_hash = None
            if existing["ids"] and manifest_hash != expected_hash:
                if not settings.auto_build_vector_store:
                    self.error = "向量索引已过期。请运行 scripts/build_openai_vector_store.py --rebuild；当前使用最新知识库的本地检索。"
                    return
                self.collection.delete(ids=existing["ids"])
                existing = {"ids": []}
            if not existing["ids"]:
                if not settings.auto_build_vector_store:
                    self.error = "向量库为空。请运行 scripts/build_openai_vector_store.py 构建；当前使用本地规则检索。"
                    return
                # Part 1: policies.json (structured, no chunking)
                texts = [f"{doc['title']}\n类别：{doc['category']}\n摘要：{doc['excerpt']}\n规则：{'；'.join(doc['guidance'])}" for doc in knowledge_base.documents]
                metadatas = [{"doc_id": doc["id"], "title": doc["title"], "category": doc["category"], "citation": doc["citation"]} for doc in knowledge_base.documents]
                ids = [doc["id"] for doc in knowledge_base.documents]
                # Part 2: markdown SOP docs (chunked)
                md_texts, md_metadatas, md_ids = _load_and_chunk_markdown_docs(KB_DIR)
                texts.extend(md_texts)
                metadatas.extend(md_metadatas)
                ids.extend(md_ids)
                vectors = self.embeddings.embed_documents(texts)
                self.collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=vectors)
                manifest_path.write_text(json.dumps({"knowledge_base_hash": expected_hash}, ensure_ascii=False, indent=2), encoding="utf-8")
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
            context = "\n\n".join(
                f"[{doc['citation']}] {doc['title']}\n{doc['excerpt']}\n处理指引：{'；'.join(doc.get('guidance', []))}"
                for doc in docs
            ) or "未检索到明确条款"
            prompt = (
                "你是企业级售后客诉 Copilot。只允许依据给定 SOP 证据回答，不得编造规则或承诺执行退款。"
                "请先给明确结论，再给依据和下一步；证据不足时明确建议人工复核。"
                "回答最多 6 句话，禁止输出 Markdown 表格、代码块或逐行复述订单明细。\n\n"
                f"问题：{question}\n\nSOP 证据：\n{context}"
            )
            generation_start = time.perf_counter()
            model_trace: list[dict[str, Any]] = []
            generation_error: str | None = None
            if self.generation_client:
                try:
                    response = self.generation_client.chat.completions.create(
                        model=self.settings.llm_model,
                        temperature=0,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    answer = response.choices[0].message.content or "模型未返回有效内容，建议转人工复核。"
                    token_usage = {"embedding_tokens": 0, **extract_usage(response)}
                    model_trace.append({"stage": "rag_synthesis", "model": self.settings.llm_model, "provider": "openai_compatible"})
                except Exception as exc:
                    generation_error = str(exc)
                    answer = "模型生成失败，已保留检索证据，建议转人工复核。"
                    estimated = estimate_text_tokens(answer)
                    token_usage = {"embedding_tokens": 0, "prompt_tokens": 0, "completion_tokens": estimated, "total_tokens": estimated}
            else:
                answer = "未配置语言模型，已保留检索证据，建议转人工复核。"
                estimated = estimate_text_tokens(answer)
                token_usage = {"embedding_tokens": 0, "prompt_tokens": 0, "completion_tokens": estimated, "total_tokens": estimated}
            generation_ms = round((time.perf_counter() - generation_start) * 1000, 2)
            return {
                "available": False,
                "answer": answer,
                "sources": fallback_sources,
                "fallback_reason": generation_error,
                "retrieval_mode": "lexical",
                "generation_mode": "llm" if model_trace else "deterministic_fallback",
                "retrieval_ms": retrieval_ms,
                "embedding_ms": 0,
                "generation_ms": generation_ms,
                "total_ms": round((time.perf_counter() - start) * 1000, 2),
                "token_usage": token_usage,
                "cost_breakdown": estimate_cost_breakdown(self.settings, token_usage),
                "model_trace": model_trace,
            }
        embedding_start = time.perf_counter()
        query_vector = self.embeddings.embed_query(question)
        embedding_ms = round((time.perf_counter() - embedding_start) * 1000, 2)
        retrieval_start = time.perf_counter()
        query_kwargs: dict[str, Any] = {
            "query_embeddings": [query_vector],
            "n_results": max(top_k * 2, 6),
        }
        if category:
            query_kwargs["where"] = {"$or": [{"category": category}, {"category": "通用"}]}
        result = self.collection.query(**query_kwargs)
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
            "retrieval_mode": "vector",
            "generation_mode": "llm" if self.llm else "deterministic_fallback",
            "model_trace": [{"stage": "rag_synthesis", "model": self.settings.llm_model, "provider": "openai_compatible"}] if self.llm else [],
        }
