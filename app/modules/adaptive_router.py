from __future__ import annotations

import re
from typing import Any

from app.modules.base import RAGContext, RAGModule


MULTI_HOP_MARKERS = ["为什么", "原因", "导致", "引起", "影响", "关联", "关系", "链路", "追溯", "根因"]
COMPLEX_MARKERS = ["并且", "同时", "顺便", "另外", "还有", "以及", "然后", "接着", "对比", "比较"]


class AdaptiveRouterModule(RAGModule):
    """Selects retrieval strategy based on query complexity."""
    name = "adaptive_router"

    def __init__(self):
        self.enabled = True

    def should_activate(self, context: RAGContext) -> bool:
        return True

    async def execute(self, context: RAGContext) -> RAGContext:
        query = context.rewritten_query or context.query
        strategy = self._analyze_complexity(query)
        context.retrieval_strategy = strategy
        context.metadata["adaptive_router"] = {
            "strategy": strategy,
            "query_length": len(query),
            "reason": self._explain_strategy(query, strategy),
        }
        return context

    def _analyze_complexity(self, query: str) -> str:
        # Multi-hop: contains causal/reasoning markers
        for marker in MULTI_HOP_MARKERS:
            if marker in query:
                return "hybrid_with_kg"

        # Complex: contains conjunction markers or multiple questions
        for marker in COMPLEX_MARKERS:
            if marker in query:
                return "hybrid"

        if re.search(r"[?？].*[?？]", query):
            return "hybrid"

        # Simple: short query with no complexity signals
        if len(query) < 20:
            return "lexical"

        return "hybrid"

    def _explain_strategy(self, query: str, strategy: str) -> str:
        if strategy == "hybrid_with_kg":
            return "查询包含因果/推理关键词，启用图谱+向量混合检索"
        if strategy == "hybrid":
            return "查询较复杂，启用向量+词法混合检索"
        return "查询较简单，使用词法检索"
