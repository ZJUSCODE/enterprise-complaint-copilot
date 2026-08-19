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

from app.bm25 import BM25Index, reciprocal_rank_fusion
from app.config import Settings, KB_DIR, VECTOR_DIR
from app.retrieval_backend import WeKnoraBackend
from app.utils import (
    estimate_cost_breakdown,
    estimate_text_tokens,
    extract_usage,
    extract_langchain_usage,
    lexical_overlap_score,
    summarize_text,
)


VECTOR_MANIFEST = "kb_manifest.json"

# 文件名/路径关键字 -> 品类（与 policies.json 的 category 体系对齐）
_CATEGORY_RULES: list[tuple[str, str]] = [
    ("3c", "3C数码"),
    ("digital", "3C数码"),
    ("数码", "3C数码"),
    ("fresh", "生鲜"),
    ("生鲜", "生鲜"),
    ("food", "食品"),
    ("食品", "食品"),
    ("apparel", "服饰"),
    ("服饰", "服饰"),
    ("home", "家居"),
    ("furnishing", "家居"),
    ("家居", "家居"),
    ("beauty", "美妆"),
    ("cosmetic", "美妆"),
    ("美妆", "美妆"),
    ("logistics", "物流"),
    ("物流", "物流"),
    ("refund", "退款"),
    ("退款", "退款"),
    ("invoice", "通用"),
    ("发票", "通用"),
    ("member", "通用"),
    ("会员", "通用"),
]


def _infer_category(path: Path, name_lower: str) -> str:
    """根据文件路径与文件名推断 md 文档的品类。"""
    rel = path.as_posix().lower()
    for keyword, category in _CATEGORY_RULES:
        if keyword in name_lower or keyword in rel:
            return category
    return "通用"


def knowledge_base_hash(kb_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted([kb_dir / "policies.json", *kb_dir.glob("**/*.md")]):
        if not path.exists() or path.name.lower().startswith("readme"):
            continue
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _load_and_chunk_markdown_docs(kb_dir: Path) -> tuple[list[str], list[dict], list[str]]:
    """Load *.md files from kb_dir (recursively), split into chunks for vector indexing."""
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

    for md_file in sorted(kb_dir.glob("**/*.md")):
        if md_file.name.lower().startswith("readme"):
            continue
        content = md_file.read_text(encoding="utf-8")
        chunks = splitter.split_text(content)
        if not chunks:
            continue
        name_lower = md_file.name.lower()
        first_heading = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        doc_title = first_heading.group(1).strip() if first_heading else md_file.stem
        category = _infer_category(md_file.relative_to(kb_dir), name_lower)

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
        # BM25 稀疏索引：不依赖 embedding，任何情况下都尝试构建（词法兜底升级）
        self.bm25_index = BM25Index()
        self.bm25_error: str | None = None
        self.weknora_backend: WeKnoraBackend | None = None
        self._corpus_metas: dict[str, dict] = {}
        self._corpus_texts: dict[str, str] = {}
        texts: list[str] = []
        metadatas: list[dict] = []
        ids: list[str] = []

        # WeKnora 外部检索后端：启用时替换检索层，回答生成仍走本地 LLM
        if settings.retrieval_backend == "weknora":
            self.weknora_backend = WeKnoraBackend(
                base_url=settings.weknora_base_url,
                api_key=settings.weknora_api_key,
                kb_id=settings.weknora_kb_id,
            )
            if not self.weknora_backend.available:
                self.error = "WeKnora 模式缺少配置（WEKNORA_BASE_URL / WEKNORA_API_KEY / WEKNORA_KB_ID）。"
            elif not settings.llm_api_key:
                self.error = "WeKnora 模式需要 LLM_API_KEY 用于回答生成。"
                self.weknora_backend = None

        # 语料 = policies.json（结构化）+ 全量 md chunks，供向量索引与 BM25 共用
        try:
            texts, metadatas, ids = self._build_corpus()
            self._corpus_metas = {m.get("doc_id", ""): m for m in metadatas}
            self._corpus_texts = dict(zip(ids, texts))
            self.bm25_index.build(ids, texts, [m.get("category", "") for m in metadatas])
        except Exception as exc:
            self.bm25_error = f"BM25 索引构建失败：{exc}"

        if not settings.use_langchain_rag or not settings.embedding_api_key or not settings.llm_api_key:
            self.error = "向量 Embedding 未启用；当前使用本地词法/BM25 检索 + 大模型生成。"
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
                # Part 2: markdown SOP docs (chunked) —— 由 _build_corpus 统一产出
                vectors = self.embeddings.embed_documents(texts)
                self.collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=vectors)
                manifest_path.write_text(json.dumps({"knowledge_base_hash": expected_hash}, ensure_ascii=False, indent=2), encoding="utf-8")
            self.llm = ChatOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, model=settings.llm_model, temperature=0)
            self.available = True
        except Exception as exc:
            self.error = f"向量库初始化失败：{exc}。当前使用本地规则检索。"

    def _build_corpus(self) -> tuple[list[str], list[dict], list[str]]:
        """policies.json 结构化条目 + 全部 md 分块，统一为 (texts, metadatas, ids)。"""
        texts = [f"{doc['title']}\n类别：{doc['category']}\n摘要：{doc['excerpt']}\n规则：{'；'.join(doc['guidance'])}" for doc in self.knowledge_base.documents]
        metadatas = [{"doc_id": doc["id"], "title": doc["title"], "category": doc["category"], "citation": doc["citation"]} for doc in self.knowledge_base.documents]
        ids = [doc["id"] for doc in self.knowledge_base.documents]
        md_texts, md_metadatas, md_ids = _load_and_chunk_markdown_docs(KB_DIR)
        texts.extend(md_texts)
        metadatas.extend(md_metadatas)
        ids.extend(md_ids)
        return texts, metadatas, ids

    def _query_with_weknora(
        self, question: str, category: str | None, top_k: int, start: float
    ) -> dict[str, Any] | None:
        """用 WeKnora 检索 + 本地 LLM 生成。检索失败返回 None 以便回退。"""
        retrieval_start = time.perf_counter()
        sources = self.weknora_backend.search(question, top_k=top_k, category=category)
        retrieval_ms = round((time.perf_counter() - retrieval_start) * 1000, 2)
        if not sources:
            return None
        context = "\n\n".join([f"[{item['citation']}] {item['title']} - {item['excerpt']}" for item in sources])
        prompt = "你是企业级售后 Copilot。请只基于给定上下文回答，不能编造规则。如果上下文不足，请明确说需要人工复核。\n\n" + f"问题：{question}\n\n上下文：\n{context}"
        generation_start = time.perf_counter()
        model_trace: list[dict[str, Any]] = []
        try:
            if self.llm:
                llm_message = self.llm.invoke(prompt)
                answer = llm_message.content
                token_usage = {"embedding_tokens": 0, **extract_langchain_usage(llm_message, prompt=prompt, answer=answer)}
            elif self.generation_client:
                response = self.generation_client.chat.completions.create(
                    model=self.settings.llm_model,
                    temperature=0,
                    messages=[{"role": "user", "content": prompt}],
                )
                answer = response.choices[0].message.content or "模型未返回有效内容，建议转人工复核。"
                token_usage = {"embedding_tokens": 0, **extract_usage(response)}
            else:
                answer = "未配置语言模型，已保留检索证据，建议转人工复核。"
                token_usage = {"embedding_tokens": 0, "prompt_tokens": 0, "completion_tokens": estimate_text_tokens(answer), "total_tokens": estimate_text_tokens(answer)}
            model_trace.append({"stage": "rag_synthesis", "model": self.settings.llm_model, "provider": "weknora_retrieval"})
        except Exception as exc:
            answer = f"回答生成失败：{exc}。已保留 WeKnora 检索证据。"
            token_usage = {"embedding_tokens": 0, "prompt_tokens": 0, "completion_tokens": estimate_text_tokens(answer), "total_tokens": estimate_text_tokens(answer)}
        generation_ms = round((time.perf_counter() - generation_start) * 1000, 2)
        return {
            "available": True,
            "answer": answer,
            "sources": sources,
            "retrieval_mode": "weknora",
            "generation_mode": "llm",
            "retrieval_ms": retrieval_ms,
            "embedding_ms": 0,
            "generation_ms": generation_ms,
            "total_ms": round((time.perf_counter() - start) * 1000, 2),
            "token_usage": token_usage,
            "cost_breakdown": estimate_cost_breakdown(self.settings, token_usage),
            "model_trace": model_trace,
        }

    def _bm25_sources(self, question: str, category: str | None, top_k: int) -> list[dict[str, Any]]:
        """用 BM25 稀疏检索产出 sources（向量不可用时的词法兜底）。

        政策条目（id 以 POL- 开头）是判责锚点，BM25 在多取后对政策加权，
        避免政策被更长的 FAQ/SOP chunk 挤出 top_k；FAQ/SOP 仍可命中补充口径。
        """
        # 多取候选再做政策加权重排，保证加权后数量充足
        hits = self.bm25_index.search(question, category=category, top_k=max(top_k * 3, 9))
        weighted: list[tuple[str, float, float]] = []
        for idx, score in hits:
            doc_id = self.bm25_index._ids[idx]
            weight = 1.5 if str(doc_id).startswith("POL-") else 1.0
            weighted.append((doc_id, score * weight, score))
        weighted.sort(key=lambda item: item[1], reverse=True)
        weighted = weighted[:top_k]

        sources: list[dict[str, Any]] = []
        for doc_id, weighted_score, raw_score in weighted:
            meta = self._corpus_metas.get(doc_id, {})
            text = self._corpus_texts.get(doc_id, "")
            excerpt = text if len(text) <= 220 else summarize_text(text, limit=220)
            sources.append({
                "id": doc_id,
                "title": meta.get("title", ""),
                "category": meta.get("category", ""),
                "citation": meta.get("citation", doc_id),
                "excerpt": excerpt,
                "retrieval_score": round(max(0.0, min(1.0, raw_score / 10.0)), 4),
                "rerank_score": round(lexical_overlap_score(question, f"{meta.get('title', '')} {text}"), 4),
                "source": "bm25",
                "is_policy": bool(str(doc_id).startswith("POL-")),
            })
        return sources

    def query(self, question: str, category: str | None = None, top_k: int = 3) -> dict[str, Any]:
        start = time.perf_counter()
        # ---------- WeKnora 外部检索后端（可切换） ----------
        if self.weknora_backend is not None and self.weknora_backend.available:
            result = self._query_with_weknora(question, category=category, top_k=top_k, start=start)
            if result is not None:
                return result
            # WeKnora 检索失败/无结果 → 回退本地 BM25/词法
        # ---------- 向量不可用：BM25 / 词法兜底路径 ----------
        if not self.available or not self.collection or not self.embeddings:
            retrieval_start = time.perf_counter()
            bm25_ok = self.bm25_index.size > 0
            if bm25_ok:
                docs = self._bm25_sources(question, category=category, top_k=top_k)
                fallback_sources = docs
                retrieval_mode = "bm25_fallback"
            else:
                docs = self.knowledge_base.lexical_search(question, category=category, top_k=top_k)
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
                retrieval_mode = "lexical"
            retrieval_ms = round((time.perf_counter() - retrieval_start) * 1000, 2)
            context = "\n\n".join(
                f"[{item['citation']}] {item['title']}\n{item['excerpt']}"
                for item in fallback_sources
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
                "retrieval_mode": retrieval_mode,
                "generation_mode": "llm" if model_trace else "deterministic_fallback",
                "retrieval_ms": retrieval_ms,
                "embedding_ms": 0,
                "generation_ms": generation_ms,
                "total_ms": round((time.perf_counter() - start) * 1000, 2),
                "token_usage": token_usage,
                "cost_breakdown": estimate_cost_breakdown(self.settings, token_usage),
                "model_trace": model_trace,
            }
        # ---------- 向量可用：双路召回 + RRF 融合 ----------
        embedding_start = time.perf_counter()
        query_vector = self.embeddings.embed_query(question)
        embedding_ms = round((time.perf_counter() - embedding_start) * 1000, 2)
        retrieval_start = time.perf_counter()
        query_kwargs: dict[str, Any] = {
            "query_embeddings": [query_vector],
            "n_results": max(self.settings.hybrid_vector_candidates, 1),
        }
        if category:
            query_kwargs["where"] = {"$or": [{"category": category}, {"category": "通用"}]}
        result = self.collection.query(**query_kwargs)
        retrieval_ms = round((time.perf_counter() - retrieval_start) * 1000, 2)

        # 候选池：向量 + BM25（数量可用环境变量调优）
        vector_ranked: list[str] = []
        vector_scores: dict[str, float] = {}
        distances = result.get("distances", [[]])[0] if result.get("distances") else []
        for index, (metadata, document) in enumerate(zip(result.get("metadatas", [[]])[0], result.get("documents", [[]])[0])):
            doc_id = metadata.get("doc_id", "")
            if not doc_id:
                continue
            distance = float(distances[index]) if index < len(distances) else 1.0
            vector_ranked.append(doc_id)
            vector_scores[doc_id] = max(0.0, 1.0 - distance)
        # 向量门控：相似度低于阈值不进融合池（默认 0 不启用）
        if self.settings.hybrid_vector_threshold > 0:
            vector_ranked = [did for did in vector_ranked if vector_scores.get(did, 0.0) >= self.settings.hybrid_vector_threshold]

        bm25_ok = self.bm25_index.size > 0
        bm25_ranked: list[str] = []
        bm25_scores: dict[str, float] = {}
        if bm25_ok:
            hits = self.bm25_index.search(question, category=category, top_k=max(self.settings.hybrid_bm25_candidates, 1))
            # 政策锚点加权（POL- 条目 ×hybrid_policy_weight，默认 1.0），与 _bm25_sources 单路口径一致
            weighted_bm25: list[tuple[str, float, float]] = []
            for idx, score in hits:
                doc_id = self.bm25_index._ids[idx]
                w = self.settings.hybrid_policy_weight if str(doc_id).startswith("POL-") else 1.0
                weighted_bm25.append((doc_id, score * w, score))
            weighted_bm25.sort(key=lambda item: item[1], reverse=True)
            for doc_id, _wscore, raw_score in weighted_bm25:
                bm25_ranked.append(doc_id)
                bm25_scores[doc_id] = raw_score

        if bm25_ok:
            fused = reciprocal_rank_fusion(
                [vector_ranked, bm25_ranked],
                k=self.settings.hybrid_rrf_k,
                weights=[1.0, self.settings.hybrid_bm25_weight],
            )
        else:
            fused = [(did, 1.0) for did in vector_ranked]
        top_ids = [doc_id for doc_id, _ in fused[:top_k]]

        matched: list[dict[str, Any]] = []
        for doc_id in top_ids:
            meta = self._corpus_metas.get(doc_id, {})
            text = self._corpus_texts.get(doc_id, "")
            from_vec = doc_id in vector_scores
            from_bm25 = doc_id in bm25_scores
            source_tag = "hybrid" if (from_vec and from_bm25) else ("vector" if from_vec else "bm25")
            matched.append({
                "id": doc_id,
                "title": meta.get("title", ""),
                "category": meta.get("category", ""),
                "citation": meta.get("citation", doc_id),
                "excerpt": summarize_text(text, limit=220) if len(text) > 220 else text,
                "retrieval_score": round(vector_scores.get(doc_id, 0.0), 4),
                "bm25_score": round(bm25_scores.get(doc_id, 0.0), 4) if bm25_ok else 0.0,
                "rerank_score": round(lexical_overlap_score(question, f"{meta.get('title', '')} {text}"), 4),
                "source": source_tag,
            })
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
            "retrieval_mode": "hybrid_bm25" if bm25_ok else "vector",
            "generation_mode": "llm" if self.llm else "deterministic_fallback",
            "model_trace": [{"stage": "rag_synthesis", "model": self.settings.llm_model, "provider": "openai_compatible"}] if self.llm else [],
        }
