from __future__ import annotations

import re
from typing import Any

from openai import OpenAI

from app.config import Settings
from app.domain import POLICY_PATTERNS, SOCIAL_ENGINEERING_PATTERNS, contains_any
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
        has_risk = contains_any(message, ["风险", "风险分", "用户", "risk"])

        # Policy-with-amount: "退款需要哪些SOP依据" -> policy intent wins over data intent
        # But NOT when data keywords like "明细/统计/超过" indicate actual data query
        has_policy_with_amount = (
            contains_any(message, ["依据", "SOP", "政策", "规则", "条款", "规范", "怎么处理", "应该怎么"])
            and contains_any(message, ["退款", "赔付"])
            and contains_any(message, ["元", "金额", "多少"])
            and not contains_any(message, ["明细", "统计", "超过", "top", "最多"])
        )
        if has_policy_with_amount:
            return {"mode": "langchain_rag", "reason": "问题包含金额但核心意图是查询政策依据，走政策检索。", "confidence": 0.88, "source": "rule"}

        if has_query and has_policy and has_risk:
            return {"mode": "multi_agent", "reason": "问题同时包含数据查询、政策判断和风险评估，使用多智能体协同。", "confidence": 0.92, "source": "rule"}
        if has_query and has_policy:
            return {"mode": "sql_rag_chain", "reason": "问题同时包含数据查询与规则判断，先查只读 SQL，再检索 SOP 依据。", "confidence": 0.9, "source": "rule"}
        if has_policy:
            return {"mode": "langchain_rag", "reason": "命中政策、规则、SOP 类问题。", "confidence": 0.84, "source": "rule"}
        if has_query:
            return {"mode": "function_call_agent", "reason": "命中退款、明细、风险或统计查询规则。", "confidence": 0.82, "source": "rule"}

        # Ambiguous general queries: "最近的售后情况怎么样？" -> default to RAG for conversational answer
        if re.search(r"(怎么样|如何|情况|什么|哪些|哪些方面|需要注意)", message) and not has_query:
            return {"mode": "langchain_rag", "reason": "模糊咨询类问题，默认使用政策检索生成回答。", "confidence": 0.7, "source": "rule"}

        return None

    def _llm_route(self, message: str) -> dict[str, Any] | None:
        if not self.client:
            return None
        response = self.client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=0,
            messages=[
                {"role": "system", "content": "你是企业内 Copilot 的路由器。请在 function_call_agent、langchain_rag、sql_rag_chain、modular_rag、multi_agent 之间五选一，并输出 JSON。multi_agent 适用于同时需要数据查询、政策检索和风险评估的复杂问题。"},
                {"role": "user", "content": message},
            ],
        )
        parsed = safe_json_loads(response.choices[0].message.content or "{}")
        mode = parsed.get("mode")
        if mode not in {"function_call_agent", "langchain_rag", "sql_rag_chain", "modular_rag", "multi_agent"}:
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
        return rule_decision or {"mode": "multi_agent", "reason": "未命中高置信规则，默认使用多智能体协同处理。", "confidence": 0.55, "source": "default_fallback"}
