import pytest
from app.agentic_controller import AgenticRAGController


def test_simple_query_basic_pipeline():
    ctrl = AgenticRAGController()
    modules = ctrl.decide_pipeline("你好")
    assert "query_rewrite" in modules
    assert "hybrid_retriever" in modules
    assert "generator" in modules
    assert len(modules) == 3


def test_complex_query_full_pipeline():
    ctrl = AgenticRAGController()
    modules = ctrl.decide_pipeline("查一下退款并且看物流状态")
    assert "query_planner" in modules
    assert "kg_retriever" in modules
    assert "cross_encoder_reranker" in modules
    assert "crag_corrector" in modules
    assert "self_rag_critic" in modules


def test_multi_hop_query_kg_focus():
    ctrl = AgenticRAGController()
    modules = ctrl.decide_pipeline("为什么生鲜退款率这么高")
    assert "kg_retriever" in modules
    assert "hybrid_retriever" in modules
    assert "self_rag_critic" in modules
    # Should not have query_planner for multi-hop
    assert "query_planner" not in modules


def test_complex_with_policy_and_query():
    ctrl = AgenticRAGController()
    modules = ctrl.decide_pipeline("查询退款订单的SOP处理规则")
    assert "crag_corrector" in modules
    assert "self_rag_critic" in modules


def test_multi_question_complex():
    ctrl = AgenticRAGController()
    modules = ctrl.decide_pipeline("退款政策是什么？物流延迟怎么处理？")
    assert "query_planner" in modules
    assert len(modules) >= 7
