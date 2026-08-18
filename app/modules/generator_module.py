from __future__ import annotations

from typing import Any

from app.modules.base import RAGContext, RAGModule


class GeneratorModule(RAGModule):
    """Generates an answer if one hasn't been produced by the retriever."""
    name = "generator"

    def __init__(self, llm_client: Any | None = None, model: str = "gpt-4o-mini"):
        self.enabled = True
        self._llm = llm_client
        self._model = model

    def should_activate(self, context: RAGContext) -> bool:
        return not context.answer

    async def execute(self, context: RAGContext) -> RAGContext:
        results = context.corrected_results or context.reranked_results or context.fused_results or context.vector_results
        if not results:
            context.answer = "未检索到相关文档，无法生成回答。建议转人工复核。"
            return context

        if not self._llm:
            top = results[0]
            context.answer = f"基于 {top.citation}，建议参考：{top.excerpt[:200]}"
            return context

        context_text = "\n\n".join(f"[{r.citation}] {r.title} - {r.excerpt}" for r in results[:5])
        prompt = f"你是企业级售后 Copilot。请只基于给定上下文回答，不能编造规则。\n\n问题：{context.query}\n\n上下文：\n{context_text}"
        try:
            response = self._llm.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )
            context.answer = response.choices[0].message.content or ""
        except Exception as exc:
            context.answer = f"回答生成失败：{exc}"
        return context
