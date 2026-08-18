from __future__ import annotations

from typing import Any

from app.modules.base import RAGContext, RAGModule
from app.query_planner import QueryPlanner


class QueryPlannerModule(RAGModule):
    """Wraps QueryPlanner as a pluggable module."""
    name = "query_planner"

    def __init__(self, planner: QueryPlanner):
        self.enabled = True
        self._planner = planner

    def should_activate(self, context: RAGContext) -> bool:
        plan = self._planner.plan(context.query)
        return plan.is_complex

    async def execute(self, context: RAGContext) -> RAGContext:
        plan = self._planner.plan(context.query)
        context.sub_queries = [step.query for step in plan.steps]
        context.metadata["query_plan"] = {
            "steps": [{"step_id": s.step_id, "query": s.query, "expected_tool": s.expected_tool} for s in plan.steps],
            "decomposition_method": plan.decomposition_method,
        }
        return context
