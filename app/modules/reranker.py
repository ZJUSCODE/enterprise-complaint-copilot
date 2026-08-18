from __future__ import annotations

import logging
from typing import Any

from app.modules.base import RAGContext, RAGModule, Citation

logger = logging.getLogger(__name__)


class CrossEncoderReranker(RAGModule):
    """Reranks retrieval results using a cross-encoder model."""
    name = "cross_encoder_reranker"

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.enabled = True
        self._model_name = model_name
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
                self._model = CrossEncoder(self._model_name)
                logger.info("Cross-encoder model loaded: %s", self._model_name)
            except Exception as exc:
                logger.warning("Failed to load cross-encoder: %s", exc)
                self._model = None

    def should_activate(self, context: RAGContext) -> bool:
        results = context.fused_results or context.vector_results or context.kg_results
        return len(results) > 0

    async def execute(self, context: RAGContext) -> RAGContext:
        results = context.fused_results or context.vector_results or context.kg_results
        if not results:
            context.reranked_results = []
            return context

        self._load_model()

        if self._model is None:
            # Fallback: sort by existing scores
            context.reranked_results = sorted(results, key=lambda c: c.retrieval_score, reverse=True)
            context.metadata["reranker"] = {"model": "fallback_sort", "count": len(results)}
            return context

        query = context.rewritten_query or context.query
        pairs = [(query, r.excerpt) for r in results]
        scores = self._model.predict(pairs)

        for citation, score in zip(results, scores):
            citation.rerank_score = float(score)

        reranked = sorted(results, key=lambda c: c.rerank_score, reverse=True)
        context.reranked_results = reranked
        context.metadata["reranker"] = {
            "model": self._model_name,
            "count": len(reranked),
            "top_score": round(reranked[0].rerank_score, 4) if reranked else 0.0,
        }
        return context
