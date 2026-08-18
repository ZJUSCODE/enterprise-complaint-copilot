from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import chromadb
import os

os.environ.setdefault("LANGCHAIN_OPENAI_TCP_KEEPALIVE", "0")

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import Settings, KB_DIR, VECTOR_DIR
from app.rag_metrics import compute_online_metrics
from app.utils import (
    estimate_cost_breakdown,
    estimate_text_tokens,
    extract_langchain_usage,
    lexical_overlap_score,
    summarize_text,
)


def reciprocal_rank_fusion(
    result_lists: list[list[dict[str, Any]]],
    k: int = 60,
) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    items: dict[str, dict[str, Any]] = {}
    for result_list in result_lists:
        for rank, item in enumerate(result_list, start=1):
            doc_id = item.get("id") or item.get("doc_id", str(rank))
            rrf_score = 1.0 / (k + rank)
            scores[doc_id] = scores.get(doc_id, 0.0) + rrf_score
            if doc_id not in items:
                items[doc_id] = dict(item)
            items[doc_id]["rrf_score"] = round(scores[doc_id], 6)
    return sorted(items.values(), key=lambda x: x.get("rrf_score", 0), reverse=True)


def _semantic_split_section(text: str, max_chars: int = 500) -> list[str]:
    """Split a section by sentence boundaries when it exceeds max_chars."""
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[。！？\n])", text)
    chunks: list[str] = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) > max_chars and current:
            chunks.append(current.strip())
            current = sent
        else:
            current += sent
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text]


def _load_and_chunk_markdown_docs(
    kb_dir: Path,
    cleaner: "DataCleaner | None" = None,
) -> tuple[list[str], list[dict], list[str]]:
    """Load *.md files from kb_dir, split by heading boundaries (semantic chunking).
    If a DataCleaner is provided, apply noise removal and deduplication.
    """
    from app.document.cleaner import DataCleaner
    from app.document.parsers.base import DocumentSection

    if cleaner is None:
        cleaner = DataCleaner()

    all_texts: list[str] = []
    all_metadatas: list[dict] = []
    all_ids: list[str] = []
    chunk_counter = 0

    for md_file in sorted(kb_dir.glob("*.md")):
        if md_file.name.lower().startswith("readme"):
            continue
        content = md_file.read_text(encoding="utf-8")
        if not content.strip():
            continue
        name_lower = md_file.name.lower()
        first_heading = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        doc_title = first_heading.group(1).strip() if first_heading else md_file.stem
        category = "售后" if "after_sales" in name_lower else "物流" if "logistics" in name_lower else "生鲜" if "fresh" in name_lower else "通用"

        # Primary split: by ## headings
        raw_sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
        # Wrap in DocumentSection for cleaning
        doc_sections = []
        for section in raw_sections:
            section = section.strip()
            if not section:
                continue
            heading_match = re.match(r"^##\s+(.+)$", section, re.MULTILINE)
            section_title = heading_match.group(1).strip() if heading_match else ""
            doc_sections.append(DocumentSection(
                title=section_title,
                content=section,
                section_type="heading" if section_title else "paragraph",
                metadata={"source_file": md_file.name, "doc_title": doc_title, "category": category},
            ))

        # Apply cleaning pipeline
        cleaned_sections = cleaner.clean(doc_sections)

        for section in cleaned_sections:
            section_title = section.title
            title = section_title or doc_title
            citation = f"{md_file.name} > {section_title}" if section_title else md_file.name
            parent_id = f"{md_file.stem}_section_{chunk_counter:03d}"

            # Store parent section for small-to-big retrieval
            all_texts.append(section.content)
            all_metadatas.append({
                "doc_id": parent_id,
                "title": title,
                "category": category,
                "citation": citation,
                "source_file": md_file.name,
                "section_title": section_title,
                "is_parent": True,
                "quality_score": section.metadata.get("quality_score", 0.0),
            })
            all_ids.append(parent_id)

            # Child chunks: sentence-level split for sections > 500 chars
            sub_chunks = _semantic_split_section(section.content, max_chars=500)
            for idx, sub in enumerate(sub_chunks):
                chunk_counter += 1
                child_id = f"{md_file.stem}_chunk_{chunk_counter:03d}"
                all_texts.append(sub)
                all_metadatas.append({
                    "doc_id": child_id,
                    "title": title,
                    "category": category,
                    "citation": citation,
                    "source_file": md_file.name,
                    "section_title": section_title,
                    "parent_id": parent_id,
                    "chunk_index": idx,
                    "is_parent": False,
                    "quality_score": section.metadata.get("quality_score", 0.0),
                })
                all_ids.append(child_id)

    return all_texts, all_metadatas, all_ids


def _load_and_process_documents(
    kb_dir: Path,
) -> tuple[list[str], list[dict], list[str]]:
    """Load all supported files (PDF/Word/Excel/MD) from kb_dir using the full
    document processing pipeline: parse → clean → chunk.
    Returns (texts, metadatas, ids) compatible with ChromaDB.
    """
    from app.document.parser import DocumentParser
    from app.document.cleaner import DataCleaner
    from app.document.chunking import ChunkingEngine

    parser = DocumentParser()
    cleaner = DataCleaner()
    chunker = ChunkingEngine(strategy="heading", max_chars=500)

    all_texts: list[str] = []
    all_metadatas: list[dict] = []
    all_ids: list[str] = []

    # 1. Markdown files via existing flow (with cleaning)
    md_texts, md_metas, md_ids = _load_and_chunk_markdown_docs(kb_dir, cleaner=cleaner)
    all_texts.extend(md_texts)
    all_metadatas.extend(md_metas)
    all_ids.extend(md_ids)

    # 2. Non-markdown files via DocumentParser
    for file_path in sorted(kb_dir.iterdir()):
        if not file_path.is_file():
            continue
        ext = file_path.suffix.lower()
        if ext == ".md" or ext not in parser.supported_extensions():
            continue
        if file_path.name.lower().startswith("readme"):
            continue

        try:
            sections = parser.parse(str(file_path))
            cleaned = cleaner.clean(sections)
            chunks = chunker.chunk(cleaned, source_file=file_path.name, source_type=ext)
            name_lower = file_path.name.lower()
            category = "售后" if "after_sales" in name_lower else "物流" if "logistics" in name_lower else "生鲜" if "fresh" in name_lower else "通用"
            for c in chunks:
                all_texts.append(c.text)
                all_metadatas.append({
                    "doc_id": c.metadata.chunk_id,
                    "title": c.metadata.section_title or file_path.stem,
                    "category": category,
                    "citation": f"{file_path.name} > {c.metadata.section_title}" if c.metadata.section_title else file_path.name,
                    "source_file": file_path.name,
                    "section_title": c.metadata.section_title,
                    "quality_score": c.metadata.quality_score,
                })
                all_ids.append(c.metadata.chunk_id)
        except Exception as exc:
            logger.warning("Failed to process %s: %s", file_path.name, exc)

    return all_texts, all_metadatas, all_ids


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
                # Part 1: policies.json (structured, no chunking)
                texts = [f"{doc['title']}\n类别：{doc['category']}\n摘要：{doc['excerpt']}\n规则：{'；'.join(doc['guidance'])}" for doc in knowledge_base.documents]
                metadatas = [{"doc_id": doc["id"], "title": doc["title"], "category": doc["category"], "citation": doc["citation"]} for doc in knowledge_base.documents]
                ids = [doc["id"] for doc in knowledge_base.documents]
                # Part 2: all documents via full processing pipeline (parse → clean → chunk)
                doc_texts, doc_metadatas, doc_ids = _load_and_process_documents(KB_DIR)
                texts.extend(doc_texts)
                metadatas.extend(doc_metadatas)
                ids.extend(doc_ids)
                vectors = self.embeddings.embed_documents(texts)
                self.collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=vectors)
                # Record lineage for document-sourced chunks
                try:
                    from app.config import DOCUMENT_DB_PATH
                    from app.document.lineage import LineageTracker
                    lineage = LineageTracker(DOCUMENT_DB_PATH)
                    for meta in doc_metadatas:
                        lineage.record(
                            chunk_id=meta.get("doc_id", ""),
                            source_file=meta.get("source_file", ""),
                            source_section=meta.get("section_title", ""),
                        )
                except Exception as exc:
                    logger.warning("Lineage recording failed: %s", exc)
            self.llm = ChatOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, model=settings.llm_model, temperature=0)
            self.available = True
        except Exception as exc:
            self.error = f"向量库初始化失败：{exc}。当前使用本地规则检索。"

    def _fetch_parent_context(self, parent_id: str) -> str | None:
        """Fetch the full parent section text for small-to-big retrieval."""
        if not self.collection:
            return None
        try:
            result = self.collection.get(ids=[parent_id], include=["documents"])
            docs = result.get("documents", [])
            return docs[0] if docs else None
        except Exception:
            return None

    def _vector_search(self, query: str, top_k: int = 6) -> list[dict[str, Any]]:
        if not self.available or not self.collection or not self.embeddings:
            return []
        embedding_start = time.perf_counter()
        query_vector = self.embeddings.embed_query(query)
        # Query more results to filter out parent chunks (we only want child chunks for retrieval)
        result = self.collection.query(query_embeddings=[query_vector], n_results=top_k * 2)
        distances = result.get("distances", [[]])[0] if result.get("distances") else []
        results = []
        for index, (metadata, document) in enumerate(zip(result.get("metadatas", [[]])[0], result.get("documents", [[]])[0])):
            # Skip parent chunks — they're only used for context expansion
            if metadata.get("is_parent"):
                continue
            distance = float(distances[index]) if index < len(distances) else 1.0
            retrieval_score = max(0.0, 1.0 - distance)
            parent_id = metadata.get("parent_id")
            parent_context = self._fetch_parent_context(parent_id) if parent_id else None
            excerpt_source = parent_context or document
            results.append({
                "id": metadata.get("doc_id"),
                "title": metadata.get("title"),
                "category": metadata.get("category"),
                "citation": metadata.get("citation"),
                "excerpt": summarize_text(excerpt_source, limit=300),
                "chunk_excerpt": summarize_text(document, limit=220),
                "parent_id": parent_id,
                "retrieval_score": round(retrieval_score, 4),
                "rerank_score": round(lexical_overlap_score(query, f"{metadata.get('title', '')} {document}"), 4),
                "source": "vector_search",
            })
            if len(results) >= top_k:
                break
        return sorted(results, key=lambda item: (item["rerank_score"], item["retrieval_score"]), reverse=True)

    def _lexical_search_results(self, query: str, category: str | None = None, top_k: int = 6) -> list[dict[str, Any]]:
        docs = self.knowledge_base.lexical_search(query, category=category, top_k=top_k)
        results = []
        for rank, doc in enumerate(docs, start=1):
            results.append({
                "id": doc.get("id"),
                "title": doc.get("title"),
                "category": doc.get("category"),
                "citation": doc.get("citation"),
                "excerpt": doc.get("excerpt"),
                "retrieval_score": round(1.0 - (rank - 1) * 0.1, 4),
                "rerank_score": round(lexical_overlap_score(query, f"{doc.get('title', '')} {doc.get('excerpt', '')}"), 4),
                "source": "lexical",
            })
        return results

    def query(
        self,
        question: str,
        category: str | None = None,
        top_k: int = 3,
        history: list[dict[str, str]] | None = None,
        rewritten_query: str | None = None,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        search_query = rewritten_query or question

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
            rewrite_applied = rewritten_query is not None and rewritten_query != question
            fallback_metrics = compute_online_metrics(question, fallback_sources, answer, rewrite_applied)
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
                "retrieval_mode": "lexical_fallback",
                "online_metrics": {
                    "retrieval_diversity": fallback_metrics.retrieval_diversity,
                    "retrieval_confidence": fallback_metrics.retrieval_confidence,
                    "coverage_score": fallback_metrics.coverage_score,
                    "has_citations": fallback_metrics.has_citations,
                    "query_rewrite_applied": fallback_metrics.query_rewrite_applied,
                },
            }

        retrieval_start = time.perf_counter()
        vector_results = self._vector_search(search_query, top_k=top_k * 2)
        lexical_results = self._lexical_search_results(search_query, category=category, top_k=top_k * 2)

        if vector_results and lexical_results:
            matched = reciprocal_rank_fusion([vector_results, lexical_results], k=60)[:top_k]
            retrieval_mode = "hybrid_rrf"
        elif vector_results:
            matched = vector_results[:top_k]
            retrieval_mode = "vector_only"
        else:
            matched = lexical_results[:top_k]
            retrieval_mode = "lexical_only"
        retrieval_ms = round((time.perf_counter() - retrieval_start) * 1000, 2)

        context = "\n\n".join([f"[{item['citation']}] {item['title']} - {item['excerpt']}" for item in matched])

        history_text = ""
        if history:
            recent = history[-6:]
            history_text = "\n".join(f"{m['role']}: {m['content']}" for m in recent)

        prompt_parts = ["你是企业级售后 Copilot。请只基于给定上下文回答，不能编造规则。如果上下文不足，请明确说需要人工复核。"]
        if history_text:
            prompt_parts.append(f"\n对话历史：\n{history_text}")
        prompt_parts.append(f"\n问题：{question}\n\n上下文：\n{context}")
        prompt = "\n".join(prompt_parts)

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
        embedding_tokens = estimate_text_tokens(search_query)
        token_usage = {
            "embedding_tokens": embedding_tokens,
            "prompt_tokens": int(llm_usage.get("prompt_tokens", 0)),
            "completion_tokens": int(llm_usage.get("completion_tokens", 0)),
            "total_tokens": embedding_tokens + int(llm_usage.get("prompt_tokens", 0)) + int(llm_usage.get("completion_tokens", 0)),
        }
        rewrite_applied = rewritten_query is not None and rewritten_query != question
        online_metrics = compute_online_metrics(question, matched, answer, rewrite_applied)
        return {
            "available": True,
            "answer": answer,
            "sources": matched,
            "retrieval_ms": retrieval_ms,
            "embedding_ms": 0,
            "generation_ms": generation_ms,
            "total_ms": round((time.perf_counter() - start) * 1000, 2),
            "token_usage": token_usage,
            "cost_breakdown": estimate_cost_breakdown(self.settings, token_usage),
            "retrieval_mode": retrieval_mode,
            "online_metrics": {
                "retrieval_diversity": online_metrics.retrieval_diversity,
                "retrieval_confidence": online_metrics.retrieval_confidence,
                "coverage_score": online_metrics.coverage_score,
                "has_citations": online_metrics.has_citations,
                "query_rewrite_applied": online_metrics.query_rewrite_applied,
            },
        }
