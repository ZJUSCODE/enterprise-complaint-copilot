from __future__ import annotations

from typing import Any

from app.modules.base import RAGContext, RAGModule
from app.query_rewrite import QueryRewriter


class QueryRewriteModule(RAGModule):
    """Wraps QueryRewriter as a pluggable module."""
    name = "query_rewrite"

    def __init__(self, rewriter: QueryRewriter):
        self.enabled = True
        self._rewriter = rewriter

    def should_activate(self, context: RAGContext) -> bool:
        return True

    async def execute(self, context: RAGContext) -> RAGContext:
        history = context.metadata.get("history", [])
        result = self._rewriter.rewrite(context.query, history)
        context.rewritten_query = result.rewritten_query
        context.metadata["query_rewrite"] = {
            "original": result.original_query,
            "rewritten": result.rewritten_query,
            "method": result.rewrite_method,
            "rewrite_ms": result.rewrite_ms,
        }
        return context
