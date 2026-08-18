from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanStep:
    step_id: int
    query: str
    depends_on: list[int] = field(default_factory=list)
    expected_tool: str = ""


@dataclass
class QueryPlan:
    steps: list[PlanStep] = field(default_factory=list)
    is_complex: bool = False
    decomposition_method: str = "passthrough"  # "heuristic" | "llm" | "passthrough"


COMPLEX_MARKERS_ZH = ["并且", "同时", "顺便", "另外", "还有", "以及", "再", "然后", "接着"]
COMPLEX_MARKERS_EN = ["and also", "as well as", "in addition", "also", "furthermore", "additionally", "then", "after that"]
MULTI_QUESTION_PATTERN = re.compile(r"[?？].*[?？]")


class QueryPlanner:
    def __init__(self, llm_client: Any | None = None, model: str = "gpt-4o-mini"):
        self.llm_client = llm_client
        self.model = model

    def plan(self, message: str) -> QueryPlan:
        if not self._is_complex(message):
            return QueryPlan(is_complex=False, decomposition_method="passthrough")
        if self.llm_client:
            result = self._llm_plan(message)
            if result and result.is_complex:
                return result
        return self._heuristic_plan(message)

    def _is_complex(self, message: str) -> bool:
        msg_lower = message.lower()
        for marker in COMPLEX_MARKERS_ZH:
            if marker in message:
                return True
        for marker in COMPLEX_MARKERS_EN:
            if marker in msg_lower:
                return True
        if MULTI_QUESTION_PATTERN.search(message):
            return True
        return False

    def _heuristic_plan(self, message: str) -> QueryPlan:
        parts = re.split(r"[，,;；]?\s*(?:并且|同时|顺便|另外|还有|以及|然后|接着)\s*", message)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) < 2:
            parts = re.split(r"[?？]", message)
            parts = [p.strip() + "?" for p in parts if p.strip()]
        if len(parts) < 2:
            return QueryPlan(is_complex=False, decomposition_method="passthrough")

        steps = []
        for idx, part in enumerate(parts, start=1):
            tool = self._guess_tool(part)
            steps.append(PlanStep(step_id=idx, query=part, expected_tool=tool))
        return QueryPlan(steps=steps, is_complex=True, decomposition_method="heuristic")

    def _llm_plan(self, message: str) -> QueryPlan | None:
        try:
            prompt = (
                "你是一个查询规划器。将用户的复杂问题分解为多个独立子任务。\n"
                "返回 JSON 格式：{\"steps\": [{\"step_id\": 1, \"query\": \"...\", \"expected_tool\": \"...\", \"depends_on\": []}]}\n"
                "可用工具：query_refund_cases, search_policy_docs, get_user_risk, query_order_status, query_logistics_status, query_refund_eligibility, query_policy_by_market\n"
                f"\n用户问题：{message}\n\nJSON："
            )
            response = self.llm_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=500,
            )
            import json
            raw = (response.choices[0].message.content or "").strip()
            raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
            data = json.loads(raw)
            steps = [PlanStep(**s) for s in data.get("steps", [])]
            if len(steps) >= 2:
                return QueryPlan(steps=steps, is_complex=True, decomposition_method="llm")
        except Exception:
            pass
        return None

    def _guess_tool(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["物流", "快递", "配送", "logistics", "shipping"]):
            return "query_logistics_status"
        if any(w in q for w in ["订单状态", "order status"]):
            return "query_order_status"
        if any(w in q for w in ["退款资格", "能不能退", "refund eligibility"]):
            return "query_refund_eligibility"
        if any(w in q for w in ["风险", "risk"]):
            return "get_user_risk"
        if any(w in q for w in ["政策", "sop", "规则", "policy", "处理"]):
            return "search_policy_docs"
        if any(w in q for w in ["市场", "market"]):
            return "query_policy_by_market"
        return "query_refund_cases"
