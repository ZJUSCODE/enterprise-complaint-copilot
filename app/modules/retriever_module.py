from __future__ import annotations

from typing import Any

from app.modules.base import RAGContext, RAGModule, Citation
from app.rag import LangChainRAGService


class HybridRetrieverModule(RAGModule):
    """Wraps LangChainRAGService as a pluggable module."""
    name = "hybrid_retriever"

    def __init__(self, rag_service: LangChainRAGService):
        self.enabled = True
        self._rag = rag_service

    def should_activate(self, context: RAGContext) -> bool:
        return True

    async def execute(self, context: RAGContext) -> RAGContext:
        query = context.rewritten_query or context.query
        result = self._rag.query(
            question=query,
            category=context.metadata.get("category"),
            top_k=context.metadata.get("top_k", 3),
        )
        context.vector_results = [
            Citation(
                id=s.get("id", ""),
                title=s.get("title", ""),
                category=s.get("category", ""),
                citation=s.get("citation", ""),
                excerpt=s.get("excerpt", ""),
                retrieval_score=s.get("retrieval_score", 0.0),
                rerank_score=s.get("rerank_score", 0.0),
                source=s.get("source", ""),
            )
            for s in result.get("sources", [])
        ]
        context.answer = result.get("answer", "")
        context.metadata["retrieval_mode"] = result.get("retrieval_mode", "unknown")
        context.metadata["online_metrics"] = result.get("online_metrics", {})
        context.metadata["rag_token_usage"] = result.get("token_usage", {})
        context.metadata["rag_cost_breakdown"] = result.get("cost_breakdown", {})
        context.metadata["rag_timing"] = {
            "retrieval_ms": result.get("retrieval_ms", 0),
            "generation_ms": result.get("generation_ms", 0),
            "total_ms": result.get("total_ms", 0),
        }
        return context
