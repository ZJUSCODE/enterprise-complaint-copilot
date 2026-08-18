from __future__ import annotations

import logging
import re
from typing import Any, Callable

from app.modules.base import RAGContext, RAGModule, Citation

logger = logging.getLogger(__name__)


class CRAGCorrector(RAGModule):
    """Corrective RAG: evaluates retrieval quality and triggers retry with query reformulation."""
    name = "crag_corrector"

    QUALITY_THRESHOLD = 0.3
    CRITICAL_THRESHOLD = 0.1
    MAX_RETRIES = 2

    def __init__(self, retriever_fn: Callable[[str], list[Citation]] | None = None):
        self.enabled = True
        self._retriever_fn = retriever_fn

    def should_activate(self, context: RAGContext) -> bool:
        results = context.reranked_results or context.fused_results or context.vector_results
        return len(results) > 0

    async def execute(self, context: RAGContext) -> RAGContext:
        results = context.reranked_results or context.fused_results or context.vector_results
        if not results:
            context.corrected_results = []
            context.metadata["crag"] = {"status": "no_results", "retries": 0}
            return context

        avg_score = sum(r.retrieval_score or r.rerank_score or 0 for r in results) / len(results)

        if avg_score < self.CRITICAL_THRESHOLD:
            context.corrected_results = results
            context.metadata["crag"] = {
                "status": "unreliable",
                "avg_score": round(avg_score, 4),
                "retries": 0,
                "message": "检索结果质量极低，无可靠依据，建议人工复核。",
            }
            return context

        if avg_score < self.QUALITY_THRESHOLD:
            for retry in range(self.MAX_RETRIES):
                new_results = self._retry_retrieval(context, retry)
                if new_results:
                    new_avg = sum(r.retrieval_score or r.rerank_score or 0 for r in new_results) / len(new_results)
                    if new_avg > avg_score:
                        context.corrected_results = new_results
                        context.metadata["crag"] = {
                            "status": "corrected",
                            "original_avg": round(avg_score, 4),
                            "corrected_avg": round(new_avg, 4),
                            "retries": retry + 1,
                        }
                        return context

            context.corrected_results = results
            context.metadata["crag"] = {
                "status": "low_quality",
                "avg_score": round(avg_score, 4),
                "retries": self.MAX_RETRIES,
                "message": f"经过 {self.MAX_RETRIES} 次重试，检索质量仍低于阈值。",
            }
            return context

        context.corrected_results = results
        context.metadata["crag"] = {
            "status": "passed",
            "avg_score": round(avg_score, 4),
            "retries": 0,
        }
        return context

    def _retry_retrieval(self, context: RAGContext, retry_num: int) -> list[Citation]:
        """Reformulate query and re-retrieve to improve result quality."""
        query = context.rewritten_query or context.query

        # Strategy 1 (retry 0): broaden query by extracting core keywords
        # Strategy 2 (retry 1): use original query without rewrite
        if retry_num == 0:
            reformulated = self._extract_core_query(query)
        else:
            reformulated = context.query  # fall back to original

        if reformulated == query:
            return []  # No improvement possible

        # Try retriever if available
        if self._retriever_fn:
            try:
                new_results = self._retriever_fn(reformulated)
                if new_results:
                    logger.info("CRAG retry %d: reformulated '%s' → '%s', got %d results",
                                retry_num, query[:40], reformulated[:40], len(new_results))
                    return new_results
            except Exception as exc:
                logger.warning("CRAG retry %d failed: %s", retry_num, exc)

        # Fallback: re-rank existing results with the reformulated query
        return self._rerank_with_query(context, reformulated)

    def _extract_core_query(self, query: str) -> str:
        """Extract core intent by removing filler words and keeping key entities."""
        # Remove common filler patterns
        filler_patterns = [
            r"请问", r"我想问", r"能不能", r"可不可以", r"如何",
            r"怎样", r"怎么", r"什么", r"是否", r"需要",
            r"应该", r"可以", r"会", r"要",
        ]
        result = query
        for pattern in filler_patterns:
            result = re.sub(pattern, "", result)

        # Remove punctuation and extra spaces
        result = re.sub(r"[，。？！、；：“”‘’（）\s]+", " ", result).strip()

        # If too short, fall back to extracting nouns/entities
        if len(result) < 4:
            # Extract Chinese word sequences (2-6 chars) as key terms
            terms = re.findall(r"[一-鿿]{2,6}", query)
            result = " ".join(terms[:5])

        return result if result and result != query else query

    def _rerank_with_query(self, context: RAGContext, query: str) -> list[Citation]:
        """Re-score existing results using the reformulated query via lexical overlap."""
        results = context.reranked_results or context.fused_results or context.vector_results
        if not results:
            return []

        query_chars = set(re.findall(r"[一-鿿]{2,}", query.lower()))
        if not query_chars:
            return []

        for citation in results:
            text = f"{citation.title} {citation.excerpt}"
            text_chars = set(re.findall(r"[一-鿿]{2,}", text.lower()))
            if text_chars:
                overlap = len(query_chars & text_chars) / len(query_chars)
                # Blend with original score
                original = citation.retrieval_score or citation.rerank_score or 0
                citation.rerank_score = round(original * 0.3 + overlap * 0.7, 4)

        reranked = sorted(results, key=lambda c: c.rerank_score, reverse=True)
        return reranked
