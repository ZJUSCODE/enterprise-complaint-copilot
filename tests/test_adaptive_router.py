import pytest
import asyncio
from app.modules.base import RAGContext
from app.modules.adaptive_router import AdaptiveRouterModule


def test_simple_query_routes_to_lexical():
    mod = AdaptiveRouterModule()
    ctx = asyncio.run(mod.execute(RAGContext(query="退款政策")))
    assert ctx.retrieval_strategy == "lexical"


def test_complex_query_routes_to_hybrid():
    mod = AdaptiveRouterModule()
    ctx = asyncio.run(mod.execute(RAGContext(query="查一下退款并且看物流状态")))
    assert ctx.retrieval_strategy == "hybrid"


def test_multi_hop_query_routes_to_hybrid_with_kg():
    mod = AdaptiveRouterModule()
    ctx = asyncio.run(mod.execute(RAGContext(query="为什么生鲜退款率这么高，原因是什么")))
    assert ctx.retrieval_strategy == "hybrid_with_kg"


def test_multiple_questions_route_to_hybrid():
    mod = AdaptiveRouterModule()
    ctx = asyncio.run(mod.execute(RAGContext(query="退款政策是什么？物流延迟怎么处理？")))
    assert ctx.retrieval_strategy == "hybrid"


def test_long_query_routes_to_hybrid():
    mod = AdaptiveRouterModule()
    ctx = asyncio.run(mod.execute(RAGContext(query="我需要了解关于生鲜商品的退款政策以及物流延迟的处理方式")))
    assert ctx.retrieval_strategy == "hybrid"


def test_always_activates():
    mod = AdaptiveRouterModule()
    ctx = RAGContext(query="test")
    assert mod.should_activate(ctx) is True


def test_metadata_recorded():
    mod = AdaptiveRouterModule()
    ctx = asyncio.run(mod.execute(RAGContext(query="test")))
    assert "adaptive_router" in ctx.metadata
    assert "strategy" in ctx.metadata["adaptive_router"]
    assert "reason" in ctx.metadata["adaptive_router"]
