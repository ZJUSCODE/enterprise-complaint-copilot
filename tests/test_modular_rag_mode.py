from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.pipeline import ModularRAGPipeline
from app.modules.adaptive_router import AdaptiveRouterModule
from app.modules.retriever_module import HybridRetrieverModule
from app.modules.reranker import CrossEncoderReranker
from app.modules.crag import CRAGCorrector
from app.modules.self_rag import SelfRAGCritic
from app.orchestrator import Orchestrator
from app.schemas import ChatRequest
from app.permissions import PermissionPolicy
from app.config import Settings


class _FakeMemory:
    def get_or_create(self, sid):
        return sid or "sid"
    def append(self, *a, **k):
        pass


class FakeRAGService:
    """Minimal stand-in for LangChainRAGService.query()."""

    def query(self, question, category=None, top_k=3):
        return {
            "answer": (
                f"依据售后 SOP，对于「{question}」建议先核验购买凭证与故障描述，"
                "再按类目走退款或换货流程；3C 数码类优先换货。"
            ),
            "sources": [
                {"id": "sop_after_sales", "title": "售后 SOP", "category": "售后", "citation": "售后 SOP §3.2",
                 "excerpt": "拆封后质量问题需提供故障描述与照片，3C 数码类建议换货。",
                 "retrieval_score": 0.82, "rerank_score": 0.0, "source": "sop_after_sales.md"},
                {"id": "sop_3c", "title": "3C 数码 SOP", "category": "3C", "citation": "3C SOP §1.1",
                 "excerpt": "3C 数码拆封后非人为损坏可换新，需 SN 与检测报告。",
                 "retrieval_score": 0.75, "rerank_score": 0.0, "source": "sop_3c.md"},
            ],
            "retrieval_mode": "vector",
            "token_usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            "cost_breakdown": {},
            "total_ms": 5,
        }


def _build_pipeline(rag_service):
    return ModularRAGPipeline(modules=[
        AdaptiveRouterModule(),
        HybridRetrieverModule(rag_service),
        CrossEncoderReranker(),
        CRAGCorrector(lambda q: []),
        SelfRAGCritic(None, model="gpt-4o-mini"),
    ])


def test_modular_rag_schema_accepts_mode():
    req = ChatRequest(message="3C 拆封质量问题怎么处理", mode="modular_rag")
    assert req.mode == "modular_rag"
    with pytest.raises(ValidationError):
        ChatRequest(message="x", mode="not_a_mode")


def test_modular_rag_permission_allowed():
    assert PermissionPolicy.can_use_mode("viewer", "modular_rag")
    assert PermissionPolicy.can_use_mode("analyst", "modular_rag")
    assert PermissionPolicy.can_use_mode("supervisor", "modular_rag")


@patch.object(CrossEncoderReranker, "_load_model", lambda self: None)
def test_modular_rag_pipeline_runs_end_to_end():
    pipeline = _build_pipeline(FakeRAGService())
    ctx = asyncio.run(pipeline.run("3C 数码拆封后质量问题怎么处理", {"category": "3C", "top_k": 5}))
    assert ctx.answer
    assert ctx.vector_results
    assert ctx.reranked_results
    assert "adaptive_router" in ctx.metadata
    assert "reranker" in ctx.metadata
    assert "crag" in ctx.metadata
    assert "self_rag" in ctx.metadata
    assert "hybrid_retriever" in ctx.metadata.get("activated_modules", [])


@patch.object(CrossEncoderReranker, "_load_model", lambda self: None)
def test_format_modular_rag_response_shape():
    pipeline = _build_pipeline(FakeRAGService())
    ctx = asyncio.run(pipeline.run("3C 数码拆封后质量问题怎么处理", {"category": "3C", "top_k": 5}))
    resp = Orchestrator._format_modular_rag_response(ctx, "3C 数码拆封后质量问题怎么处理", "sid-1", "3C")
    assert resp["mode"] == "modular_rag"
    assert resp["summary"] == ctx.answer
    assert isinstance(resp["citations"], list) and resp["citations"]
    assert resp["citations"][0]["label"]
    assert isinstance(resp["tool_trace"], list) and resp["tool_trace"]
    assert "激活模块" in resp["highlights"][1]
    assert resp["_token_usage"]["total_tokens"] == 30


def test_respond_modular_rag_glue_real_path():
    """Exercise the real _respond_modular_rag glue (lazy pipeline build + asyncio.run)."""
    orch = object.__new__(Orchestrator)
    orch.settings = Settings()
    orch.settings.llm_api_key = ""
    orch.langchain_rag = FakeRAGService()
    orch.memory = _FakeMemory()
    orch._modular_pipeline = None
    resp = orch._respond_modular_rag("3C 数码拆封后质量问题怎么处理", session_id="sid-x")
    assert resp["mode"] == "modular_rag"
    assert resp["summary"]
    assert resp["citations"]
    assert resp["session_id"] == "sid-x"
    # pipeline built lazily and cached
    assert orch._modular_pipeline is not None
