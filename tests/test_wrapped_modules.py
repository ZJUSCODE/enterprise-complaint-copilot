import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from app.modules.base import RAGContext, Citation
from app.modules.query_rewrite_module import QueryRewriteModule
from app.modules.query_planner_module import QueryPlannerModule
from app.modules.retriever_module import HybridRetrieverModule
from app.modules.generator_module import GeneratorModule
from app.query_rewrite import QueryRewriteResult
from app.query_planner import QueryPlan, PlanStep


def test_query_rewrite_module_always_activates():
    rewriter = MagicMock()
    mod = QueryRewriteModule(rewriter)
    ctx = RAGContext(query="test")
    assert mod.should_activate(ctx) is True


def test_query_rewrite_module_executes():
    rewriter = MagicMock()
    rewriter.rewrite.return_value = QueryRewriteResult(
        rewritten_query="rewritten",
        original_query="test",
        rewrite_method="passthrough",
        rewrite_ms=0.0,
    )
    mod = QueryRewriteModule(rewriter)
    ctx = asyncio.run(mod.execute(RAGContext(query="test")))
    assert ctx.rewritten_query == "rewritten"
    assert ctx.metadata["query_rewrite"]["method"] == "passthrough"


def test_query_planner_activates_for_complex():
    planner = MagicMock()
    planner.plan.return_value = QueryPlan(
        steps=[PlanStep(step_id=1, query="q1"), PlanStep(step_id=2, query="q2")],
        is_complex=True,
        decomposition_method="heuristic",
    )
    mod = QueryPlannerModule(planner)
    ctx = RAGContext(query="查一下退款并且看物流")
    assert mod.should_activate(ctx) is True


def test_query_planner_skips_simple():
    planner = MagicMock()
    planner.plan.return_value = QueryPlan(is_complex=False, decomposition_method="passthrough")
    mod = QueryPlannerModule(planner)
    ctx = RAGContext(query="退款政策")
    assert mod.should_activate(ctx) is False


def test_retriever_module_always_activates():
    rag = MagicMock()
    mod = HybridRetrieverModule(rag)
    ctx = RAGContext(query="test")
    assert mod.should_activate(ctx) is True


def test_retriever_module_executes():
    rag = MagicMock()
    rag.query.return_value = {
        "answer": "test answer",
        "sources": [{"id": "1", "title": "T", "category": "售后", "citation": "doc.md", "excerpt": "text", "retrieval_score": 0.9, "rerank_score": 0.8, "source": "vector"}],
        "retrieval_mode": "hybrid_rrf",
        "online_metrics": {},
        "token_usage": {},
        "cost_breakdown": {},
        "retrieval_ms": 10,
        "generation_ms": 20,
        "total_ms": 30,
    }
    mod = HybridRetrieverModule(rag)
    ctx = asyncio.run(mod.execute(RAGContext(query="test")))
    assert ctx.answer == "test answer"
    assert len(ctx.vector_results) == 1
    assert ctx.vector_results[0].id == "1"


def test_generator_skips_when_answer_exists():
    gen = GeneratorModule()
    ctx = RAGContext(query="test", answer="already answered")
    assert gen.should_activate(ctx) is False


def test_generator_activates_when_no_answer():
    gen = GeneratorModule()
    ctx = RAGContext(query="test", answer="")
    assert gen.should_activate(ctx) is True


def test_generator_uses_top_result_without_llm():
    gen = GeneratorModule(llm_client=None)
    ctx = RAGContext(query="test")
    ctx.vector_results = [Citation(id="1", title="T", citation="doc.md", excerpt="some guidance text")]
    ctx = asyncio.run(gen.execute(ctx))
    assert "doc.md" in ctx.answer
