from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.domain import POLICY_PATTERNS, QUERY_PATTERNS, contains_any


FOLLOWUP_MARKERS = ["那", "这个", "它", "如果", "那么", "这种", "这种情况下", "上面", "刚才", "之前", "that", "what about", "and the", "how about"]


@dataclass
class QueryRewriteResult:
    rewritten_query: str
    original_query: str
    rewrite_method: str  # "llm" | "rule_based" | "passthrough"
    rewrite_ms: float = 0.0


class QueryRewriter:
    def __init__(self, llm_client: Any | None = None, model: str = "gpt-4o-mini"):
        self.llm_client = llm_client
        self.model = model

    def rewrite(self, message: str, history: list[dict[str, str]]) -> QueryRewriteResult:
        if not history or len(history) < 2:
            return QueryRewriteResult(
                rewritten_query=message,
                original_query=message,
                rewrite_method="passthrough",
            )
        if not self._is_followup(message):
            return QueryRewriteResult(
                rewritten_query=message,
                original_query=message,
                rewrite_method="passthrough",
            )
        start = time.perf_counter()
        if self.llm_client:
            rewritten = self._llm_rewrite(message, history)
            method = "llm"
        else:
            rewritten = self._rule_based_rewrite(message, history)
            method = "rule_based"
        elapsed = round((time.perf_counter() - start) * 1000, 2)
        return QueryRewriteResult(
            rewritten_query=rewritten,
            original_query=message,
            rewrite_method=method,
            rewrite_ms=elapsed,
        )

    def _is_followup(self, message: str) -> bool:
        msg = message.strip()
        if len(msg) < 12:
            return True
        msg_lower = msg.lower()
        for marker in FOLLOWUP_MARKERS:
            if msg_lower.startswith(marker):
                return True
        if contains_any(msg, POLICY_PATTERNS) or contains_any(msg, QUERY_PATTERNS):
            if len(msg) < 20:
                return True
            return False
        if re.search(r"[0-9a-f]{24,}", msg, re.IGNORECASE):
            return False
        return False

    def _llm_rewrite(self, message: str, history: list[dict[str, str]]) -> str:
        try:
            recent = history[-6:]
            history_text = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
            prompt = (
                "你是一个查询改写助手。根据对话历史，将用户的后续问题改写为一个完整的、自包含的查询。\n"
                "规则：\n"
                "1. 如果问题已经是完整的，直接返回原问题\n"
                "2. 如果问题包含代词或省略，结合历史补充完整\n"
                "3. 只返回改写后的查询，不要解释\n\n"
                f"对话历史：\n{history_text}\n\n"
                f"用户当前问题：{message}\n\n"
                "改写后的查询："
            )
            response = self.llm_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=200,
            )
            rewritten = (response.choices[0].message.content or "").strip()
            if rewritten and len(rewritten) > 3:
                return rewritten
        except Exception:
            pass
        return self._rule_based_rewrite(message, history)

    def _rule_based_rewrite(self, message: str, history: list[dict[str, str]]) -> str:
        last_assistant_topic = ""
        for item in reversed(history):
            if item.get("role") == "assistant":
                content = item.get("content", "")
                if content:
                    last_assistant_topic = content[:80]
                    break
        if not last_assistant_topic:
            for item in reversed(history):
                if item.get("role") == "user":
                    last_assistant_topic = item.get("content", "")[:80]
                    break
        if last_assistant_topic:
            return f'关于"{last_assistant_topic}"，{message}'
        return message
