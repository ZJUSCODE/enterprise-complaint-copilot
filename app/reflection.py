from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.domain import contains_any
from app.utils import lexical_overlap_score

logger = logging.getLogger(__name__)


@dataclass
class ReflectionResult:
    passed: bool
    issues: list[str] = field(default_factory=list)
    suggestion: str = ""
    retries: int = 0
    scores: dict[str, float] = field(default_factory=dict)  # faithfulness, relevance, completeness


class ReflectionEngine:
    """Answer quality checks: rule-based + optional LLM-as-judge."""

    VAGUE_PHRASES = [
        "无法直接判断",
        "未提及",
        "未说明",
        "未在上下文",
        "没有统一",
        "不存在统一",
        "上下文不足",
        "需要人工复核",
        "建议咨询",
        "无法确定",
    ]

    def __init__(self, llm_client: Any = None, model: str = "gpt-4o-mini"):
        self._llm = llm_client
        self._model = model

    def check(
        self,
        answer: str,
        query: str,
        citations: list[dict[str, Any]] | None = None,
    ) -> ReflectionResult:
        issues: list[str] = []
        scores: dict[str, float] = {}

        # ── Rule-based checks (always run, fast) ──
        rule_issues = self._rule_check(answer, query, citations)
        issues.extend(rule_issues)

        # ── LLM-as-judge (when LLM available) ──
        if self._llm and citations:
            try:
                llm_issues, llm_scores = self._llm_judge(answer, query, citations)
                issues.extend(llm_issues)
                scores.update(llm_scores)
            except Exception as exc:
                logger.warning("LLM-as-judge failed, falling back to rules only: %s", exc)

        # Allow passing with at most 1 minor issue (rule-based only);
        # require zero issues when LLM judge is active (stricter standard).
        passed = len(issues) == 0 if self._llm and citations else len(issues) <= 1
        suggestion = ""
        if not passed:
            suggestion = "请基于检索到的 SOP 依据，给出更具体的处理建议，并直接引用相关条款。"

        return ReflectionResult(
            passed=passed,
            issues=issues,
            suggestion=suggestion,
            scores=scores,
        )

    def _rule_check(
        self,
        answer: str,
        query: str,
        citations: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        issues: list[str] = []

        # 1. Citation coverage — answer should share some vocabulary with retrieved citations
        if citations and len(citations) > 0:
            citation_texts = " ".join(c.get("text", "") or c.get("label", "") for c in citations)
            overlap = lexical_overlap_score(answer, citation_texts)
            if overlap < 0.02:
                issues.append("回答未引用任何检索到的 SOP 依据。")

        # 2. Vagueness check — too many hedging phrases indicate weak answer
        vague_count = sum(1 for phrase in self.VAGUE_PHRASES if phrase in answer)
        if vague_count >= 5:
            issues.append(f"回答包含 {vague_count} 个模糊表述，可能缺乏具体建议。")

        # 3. Completeness: answer should address the query's main topic (character-level)
        query_tokens = set(re.findall(r"[一-鿿]|[a-z0-9]{2,}", query.lower()))
        answer_tokens = set(re.findall(r"[一-鿿]|[a-z0-9]{2,}", answer.lower()))
        if query_tokens:
            coverage = len(query_tokens & answer_tokens) / len(query_tokens)
            if coverage < 0.10:
                issues.append("回答与问题主题相关度低，可能偏离了用户意图。")

        # 4. Minimum length check
        if len(answer.strip()) < 20:
            issues.append("回答过短，可能缺乏必要信息。")

        return issues

    def _llm_judge(
        self,
        answer: str,
        query: str,
        citations: list[dict[str, Any]],
    ) -> tuple[list[str], dict[str, float]]:
        """Use LLM to evaluate answer quality on three dimensions."""
        context_text = "\n\n".join(
            f"[{c.get('label', '')}] {c.get('text', '')}"
            for c in citations[:5]
        )

        prompt = (
            "你是企业级售后 Copilot 的质量评审员。请评估以下回答的质量。\n\n"
            f"用户问题：{query}\n\n"
            f"检索到的依据：\n{context_text}\n\n"
            f"Copilot 回答：{answer}\n\n"
            "请从以下三个维度评分（0-10 分），并判断是否通过：\n"
            "1. faithfulness（忠实度）：回答是否基于检索依据，没有编造信息\n"
            "2. relevance（相关性）：回答是否针对用户问题\n"
            "3. completeness（完整性）：回答是否充分、有具体建议\n\n"
            '返回 JSON 格式：\n'
            '{"faithfulness": 8, "relevance": 7, "completeness": 6, '
            '"passed": true, "issues": ["具体问题1", "具体问题2"], '
            '"suggestion": "改进建议"}\n\n'
            "评分标准：6 分以下为不通过，任一维度低于 5 分则整体不通过。"
        )

        response = self._llm.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        result = json.loads(content)

        issues = result.get("issues", [])
        scores = {
            "faithfulness": result.get("faithfulness", 0),
            "relevance": result.get("relevance", 0),
            "completeness": result.get("completeness", 0),
        }

        # LLM says not passed
        if not result.get("passed", True):
            if not issues:
                issues.append("LLM 评审未通过。")

        return issues, scores
