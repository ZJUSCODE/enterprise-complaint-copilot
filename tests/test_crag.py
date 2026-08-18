import pytest
import asyncio
from app.modules.base import RAGContext, Citation
from app.modules.crag import CRAGCorrector


def test_crag_passes_high_quality():
    mod = CRAGCorrector()
    ctx = RAGContext(query="test")
    ctx.reranked_results = [
        Citation(id="1", excerpt="doc1", retrieval_score=0.8, rerank_score=0.9),
        Citation(id="2", excerpt="doc2", retrieval_score=0.7, rerank_score=0.8),
    ]
    ctx = asyncio.run(mod.execute(ctx))
    assert ctx.metadata["crag"]["status"] == "passed"
    assert ctx.metadata["crag"]["retries"] == 0
    assert len(ctx.corrected_results) == 2


def test_crag_flags_low_quality():
    mod = CRAGCorrector()
    ctx = RAGContext(query="test")
    ctx.reranked_results = [
        Citation(id="1", excerpt="doc1", retrieval_score=0.2, rerank_score=0.2),
        Citation(id="2", excerpt="doc2", retrieval_score=0.25, rerank_score=0.25),
    ]
    ctx = asyncio.run(mod.execute(ctx))
    assert ctx.metadata["crag"]["status"] == "low_quality"
    assert ctx.metadata["crag"]["retries"] == 2


def test_crag_marks_unreliable():
    mod = CRAGCorrector()
    ctx = RAGContext(query="test")
    ctx.reranked_results = [
        Citation(id="1", excerpt="doc1", retrieval_score=0.05, rerank_score=0.05),
    ]
    ctx = asyncio.run(mod.execute(ctx))
    assert ctx.metadata["crag"]["status"] == "unreliable"
    assert "无可靠依据" in ctx.metadata["crag"]["message"]


def test_crag_skips_without_results():
    mod = CRAGCorrector()
    ctx = RAGContext(query="test")
    assert mod.should_activate(ctx) is False


def test_crag_activates_with_results():
    mod = CRAGCorrector()
    ctx = RAGContext(query="test")
    ctx.reranked_results = [Citation(id="1", excerpt="doc")]
    assert mod.should_activate(ctx) is True
