from __future__ import annotations

import re
from typing import Any

from openai import OpenAI

from app.config import Settings
from app.domain import POLICY_PATTERNS, contains_any
from app.utils import safe_json_loads


class AutoRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url) if settings.llm_api_key else None

    def _rule_route(self, message: str) -> dict[str, Any] | None:
        if re.search(r"[0-9a-f]{24,}", message, re.IGNORECASE) and "风险" in message:
            return {"mode": "function_call_agent", "reason": "命中用户 ID 与风险查询规则。", "confidence": 0.96, "source": "rule"}
        has_structured_query = contains_any(message, ["查询", "查一下", "明细", "统计", "分析", "订单", "风险", "用户", "超过", "多少", "金额", "top", "最多"])
        has_money_query = contains_any(message, ["退款", "赔付"]) and contains_any(message, ["查询", "查一下", "明细", "统计", "分析", "订单", "用户", "风险", "超过", "多少", "金额"])
        has_query = has_structured_query or has_money_query
        has_policy = contains_any(message, POLICY_PATTERNS)
        if has_query and has_policy:
            return {"mode": "sql_rag_chain", "reason": "问题同时包含数据查询与规则判断，先查只读 SQL，再检索 SOP 依据。", "confidence": 0.9, "source": "rule"}
        if has_policy:
            return {"mode": "langchain_rag", "reason": "命中政策、规则、SOP 类问题。", "confidence": 0.84, "source": "rule"}
        if has_query:
            return {"mode": "function_call_agent", "reason": "命中退款、明细、风险或统计查询规则。", "confidence": 0.82, "source": "rule"}
        return None

    def _llm_route(self, message: str) -> dict[str, Any] | None:
        if not self.client:
            return None
        response = self.client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=0,
            messages=[
                {"role": "system", "content": "你是企业内 Copilot 的路由器。请在 function_call_agent、langchain_rag、sql_rag_chain 之间三选一，并输出 JSON。"},
                {"role": "user", "content": message},
            ],
        )
        parsed = safe_json_loads(response.choices[0].message.content or "{}")
        mode = parsed.get("mode")
        if mode not in {"function_call_agent", "langchain_rag", "sql_rag_chain"}:
            return None
        return {"mode": mode, "reason": parsed.get("reason", "LLM classifier 给出了路由决策。"), "confidence": float(parsed.get("confidence", 0.65)), "source": "llm_classifier"}

    def route(self, message: str) -> dict[str, Any]:
        rule_decision = self._rule_route(message)
        if rule_decision and rule_decision["confidence"] >= 0.8:
            return rule_decision
        try:
            llm_decision = self._llm_route(message)
            if llm_decision:
                return llm_decision
        except Exception:
            pass
        return rule_decision or {"mode": "function_call_agent", "reason": "未命中高置信规则，默认回退到 Function Calling Agent。", "confidence": 0.55, "source": "default_fallback"}
