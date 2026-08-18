import pytest
import asyncio
from app.modules.base import RAGContext, Citation
from app.modules.reranker import CrossEncoderReranker


def test_reranker_activates_with_results():
    mod = CrossEncoderReranker()
    ctx = RAGContext(query="test")
    ctx.vector_results = [Citation(id="1", excerpt="test doc")]
    assert mod.should_activate(ctx) is True


def test_reranker_skips_without_results():
    mod = CrossEncoderReranker()
    ctx = RAGContext(query="test")
    assert mod.should_activate(ctx) is False


def test_reranker_reranks_results():
    """Test that reranker produces results with rerank_scores."""
    mod = CrossEncoderReranker()
    ctx = RAGContext(query="退款政策")
    ctx.vector_results = [
        Citation(id="1", excerpt="退款流程说明", retrieval_score=0.5),
        Citation(id="2", excerpt="退款政策详情", retrieval_score=0.9),
        Citation(id="3", excerpt="退款相关规定", retrieval_score=0.7),
    ]
    ctx = asyncio.run(mod.execute(ctx))
    assert len(ctx.reranked_results) == 3
    # All results should have rerank_score set
    for c in ctx.reranked_results:
        assert c.rerank_score > 0
    # Results should be sorted by rerank_score
    assert ctx.reranked_results[0].rerank_score >= ctx.reranked_results[-1].rerank_score
    assert "reranker" in ctx.metadata


def test_reranker_handles_empty_input():
    mod = CrossEncoderReranker()
    ctx = asyncio.run(mod.execute(RAGContext(query="test")))
    assert ctx.reranked_results == []
