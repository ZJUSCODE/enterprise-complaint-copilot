from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.domain import contains_any, POLICY_PATTERNS, QUERY_PATTERNS
from app.utils import safe_json_loads

logger = logging.getLogger(__name__)

# Multi-hop reasoning markers
MULTI_HOP_MARKERS = ["为什么", "原因", "导致", "引起", "影响", "关联", "关系", "链路", "追溯", "根因"]

# Complex query markers
COMPLEX_MARKERS = ["并且", "同时", "顺便", "另外", "还有", "以及", "然后", "接着", "对比", "比较"]

# Module descriptions for LLM prompt
MODULE_DESCRIPTIONS = {
    "query_rewrite": "将指代消解和上下文补全后的查询重写为完整独立问题",
    "query_planner": "将复杂多步问题分解为子任务序列",
    "adaptive_router": "根据查询特征选择最优检索策略（向量/词法/混合）",
    "hybrid_retriever": "向量检索 + 词法检索 + RRF 融合",
    "kg_retriever": "知识图谱检索，适合多跳推理和因果关系查询",
    "cross_encoder_reranker": "对检索结果做交叉编码器精排",
    "crag_corrector": "评估检索质量，低质量时触发查询重构和重试",
    "generator": "基于检索上下文生成自然语言回答",
    "self_rag_critic": "自我评估回答质量，检查幻觉和引用准确性",
}


class AgenticRAGController:
    """Decides which modules to activate based on query characteristics."""

    # Module names matching the pipeline
    MODULE_QUERY_REWRITE = "query_rewrite"
    MODULE_QUERY_PLANNER = "query_planner"
    MODULE_ADAPTIVE_ROUTER = "adaptive_router"
    MODULE_HYBRID_RETRIEVER = "hybrid_retriever"
    MODULE_KG_RETRIEVER = "kg_retriever"
    MODULE_CROSS_ENCODER_RERANKER = "cross_encoder_reranker"
    MODULE_CRAG_CORRECTOR = "crag_corrector"
    MODULE_GENERATOR = "generator"
    MODULE_SELF_RAG_CRITIC = "self_rag_critic"

    def __init__(self, llm_client: Any | None = None, model: str = "gpt-4o-mini"):
        self.llm_client = llm_client
        self.model = model

    def decide_pipeline(self, query: str, context: dict[str, Any] | None = None) -> list[str]:
        """Return list of module names to activate."""
        # Try LLM-based decision first
        if self.llm_client:
            try:
                llm_result = self._llm_decide_pipeline(query)
                if llm_result:
                    return llm_result
            except Exception as exc:
                logger.warning("LLM pipeline decision failed, falling back to rules: %s", exc)

        # Fallback: rule-based
        return self._rule_decide_pipeline(query)

    def _llm_decide_pipeline(self, query: str) -> list[str] | None:
        """Use LLM to decide which modules to activate."""
        module_list = "\n".join(f"- {name}: {desc}" for name, desc in MODULE_DESCRIPTIONS.items())
        prompt = (
            f"你是 RAG Pipeline 的模块调度器。根据用户查询，决定需要激活哪些模块。\n\n"
            f"可用模块：\n{module_list}\n\n"
            f"规则：\n"
            f"- 所有查询至少需要 query_rewrite + hybrid_retriever + generator\n"
            f"- 涉及因果、多跳推理时加入 kg_retriever\n"
            f"- 复杂问题（多部分、对比、分解）加入 query_planner\n"
            f"- 需要高质量精排时加入 cross_encoder_reranker\n"
            f"- 检索质量可能不可靠时加入 crag_corrector\n"
            f"- 需要自我评估时加入 self_rag_critic\n\n"
            f"用户查询：{query}\n\n"
            f"请输出 JSON 格式：{{\"modules\": [\"模块名\", ...], \"reason\": \"选择原因\"}}"
        )
        response = self.llm_client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content or "{}"
        parsed = safe_json_loads(content)
        modules = parsed.get("modules", [])
        if not isinstance(modules, list):
            return None
        # Validate all module names
        valid_modules = set(MODULE_DESCRIPTIONS.keys())
        if all(m in valid_modules for m in modules) and len(modules) >= 3:
            logger.info("LLM pipeline decision: %s (reason: %s)", modules, parsed.get("reason", ""))
            return modules
        return None

    def _rule_decide_pipeline(self, query: str) -> list[str]:
        """Rule-based pipeline decision (original logic)."""
        # Multi-hop query: focus on knowledge graph
        if self._is_multi_hop(query):
            return [
                self.MODULE_QUERY_REWRITE,
                self.MODULE_ADAPTIVE_ROUTER,
                self.MODULE_KG_RETRIEVER,
                self.MODULE_HYBRID_RETRIEVER,
                self.MODULE_CROSS_ENCODER_RERANKER,
                self.MODULE_GENERATOR,
                self.MODULE_SELF_RAG_CRITIC,
            ]

        # Complex query: full pipeline
        if self._is_complex(query):
            return [
                self.MODULE_QUERY_REWRITE,
                self.MODULE_QUERY_PLANNER,
                self.MODULE_ADAPTIVE_ROUTER,
                self.MODULE_HYBRID_RETRIEVER,
                self.MODULE_KG_RETRIEVER,
                self.MODULE_CROSS_ENCODER_RERANKER,
                self.MODULE_CRAG_CORRECTOR,
                self.MODULE_GENERATOR,
                self.MODULE_SELF_RAG_CRITIC,
            ]

        # Simple query: basic RAG
        return [
            self.MODULE_QUERY_REWRITE,
            self.MODULE_HYBRID_RETRIEVER,
            self.MODULE_GENERATOR,
        ]

    def _is_complex(self, query: str) -> bool:
        """Check if query is complex (multiple parts, conjunctions)."""
        for marker in COMPLEX_MARKERS:
            if marker in query:
                return True
        if re.search(r"[?？].*[?？]", query):
            return True
        if contains_any(query, POLICY_PATTERNS) and contains_any(query, QUERY_PATTERNS):
            return True
        return False

    def _is_multi_hop(self, query: str) -> bool:
        """Check if query requires multi-hop reasoning."""
        for marker in MULTI_HOP_MARKERS:
            if marker in query:
                return True
        return False
