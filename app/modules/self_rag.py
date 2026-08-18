from __future__ import annotations

import logging
from typing import Any

from app.modules.base import RAGContext, RAGModule
from app.reflection import ReflectionEngine, ReflectionResult

logger = logging.getLogger(__name__)


class SelfRAGCritic(RAGModule):
    """Self-RAG: evaluates answer quality and triggers regeneration if needed."""
    name = "self_rag_critic"

    def __init__(self, llm_client: Any | None = None, model: str = "gpt-4o-mini"):
        self.enabled = True
        self._llm = llm_client
        self._model = model
        self._reflection = ReflectionEngine(llm_client=llm_client, model=model)

    def should_activate(self, context: RAGContext) -> bool:
        return bool(context.answer)

    async def execute(self, context: RAGContext) -> RAGContext:
        results = context.corrected_results or context.reranked_results or context.vector_results
        citations = [
            {"text": r.excerpt, "label": r.citation}
            for r in results
        ]

        # First check: rule-based reflection
        reflection = self._reflection.check(context.answer, context.query, citations)

        if reflection.passed:
            context.reflection = reflection
            context.metadata["self_rag"] = {
                "passed": True,
                "retries": 0,
                "checks": ["faithfulness", "relevance", "completeness"],
            }
            return context

        # Not passed: attempt regeneration if LLM available
        if self._llm and results:
            for retry in range(1):
                new_answer = self._regenerate(context, results)
                if new_answer:
                    new_reflection = self._reflection.check(new_answer, context.query, citations)
                    if new_reflection.passed:
                        context.answer = new_answer
                        context.reflection = new_reflection
                        context.metadata["self_rag"] = {
                            "passed": True,
                            "retries": retry + 1,
                            "checks": ["faithfulness", "relevance", "completeness"],
                        }
                        return context

        # Still not passed
        context.reflection = reflection
        context.metadata["self_rag"] = {
            "passed": False,
            "retries": 1 if self._llm else 0,
            "issues": reflection.issues,
            "suggestion": reflection.suggestion,
        }
        return context

    def _regenerate(self, context: RAGContext, results: list) -> str | None:
        """Attempt to regenerate a better answer."""
        try:
            context_text = "\n\n".join(f"[{r.citation}] {r.title} - {r.excerpt}" for r in results[:5])
            prompt = (
                "你是企业级售后 Copilot。请基于以下上下文，给出具体、有依据的回答。\n"
                "要求：\n"
                "1. 直接引用 SOP 条款\n"
                "2. 给出明确的处理建议\n"
                "3. 避免模糊表述\n\n"
                f"问题：{context.query}\n\n上下文：\n{context_text}"
            )
            response = self._llm.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            return response.choices[0].message.content
        except Exception as exc:
            logger.warning("Self-RAG regeneration failed: %s", exc)
            return None
