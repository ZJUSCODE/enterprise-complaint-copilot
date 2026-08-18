import pytest
import asyncio
from app.modules.base import RAGContext, Citation
from app.modules.self_rag import SelfRAGCritic


def test_self_rag_passes_good_answer():
    mod = SelfRAGCritic(llm_client=None)
    ctx = RAGContext(query="退款 流程 规定")
    ctx.answer = "售后 SOP 规定，退款 流程 需要提供订单号和商品照片。退款 申请提交后，客服会在24小时内处理。"
    ctx.corrected_results = [
        Citation(id="1", excerpt="退款 流程 需要提供订单号和商品照片。退款 申请提交后，客服会在24小时内处理。", citation="售后SOP.md"),
    ]
    ctx = asyncio.run(mod.execute(ctx))
    assert ctx.metadata["self_rag"]["passed"] is True


def test_self_rag_fails_vague_answer():
    mod = SelfRAGCritic(llm_client=None)
    ctx = RAGContext(query="退款政策是什么")
    ctx.answer = "无法直接判断，未提及，未说明，需要人工复核。"
    ctx.corrected_results = [
        Citation(id="1", excerpt="退款政策详情", citation="售后SOP.md"),
    ]
    ctx = asyncio.run(mod.execute(ctx))
    assert ctx.metadata["self_rag"]["passed"] is False
    assert len(ctx.metadata["self_rag"]["issues"]) > 0


def test_self_rag_skips_without_answer():
    mod = SelfRAGCritic(llm_client=None)
    ctx = RAGContext(query="test", answer="")
    assert mod.should_activate(ctx) is False


def test_self_rag_activates_with_answer():
    mod = SelfRAGCritic(llm_client=None)
    ctx = RAGContext(query="test", answer="some answer")
    assert mod.should_activate(ctx) is True


def test_self_rag_fails_short_answer():
    mod = SelfRAGCritic(llm_client=None)
    ctx = RAGContext(query="退款政策")
    ctx.answer = "不知道"
    ctx.corrected_results = [Citation(id="1", excerpt="退款政策", citation="doc.md")]
    ctx = asyncio.run(mod.execute(ctx))
    assert ctx.metadata["self_rag"]["passed"] is False
