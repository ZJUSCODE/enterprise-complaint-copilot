import pytest
import asyncio
from app.modules.base import RAGContext, RAGModule, Citation
from app.pipeline import ModularRAGPipeline


class DummyModule(RAGModule):
    """A test module that records execution."""
    name = "dummy"
    activated = False

    def __init__(self, activate: bool = True):
        self.enabled = True
        self._should_activate = activate

    async def execute(self, context: RAGContext) -> RAGContext:
        DummyModule.activated = True
        context.metadata["dummy_ran"] = True
        return context

    def should_activate(self, context: RAGContext) -> bool:
        return self._should_activate


class DisabledModule(RAGModule):
    name = "disabled"

    def __init__(self):
        self.enabled = False

    async def execute(self, context: RAGContext) -> RAGContext:
        context.metadata["disabled_ran"] = True
        return context

    def should_activate(self, context: RAGContext) -> bool:
        return True


def test_rag_context_defaults():
    ctx = RAGContext(query="test query")
    assert ctx.query == "test query"
    assert ctx.rewritten_query == ""
    assert ctx.sub_queries == []
    assert ctx.retrieval_strategy == "hybrid"
    assert ctx.vector_results == []
    assert ctx.kg_results == []
    assert ctx.fused_results == []
    assert ctx.reranked_results == []
    assert ctx.corrected_results == []
    assert ctx.answer == ""
    assert ctx.reflection is None
    assert ctx.metadata == {}


def test_citation_fields():
    c = Citation(id="1", title="Test", category="售后", citation="doc.md > section", excerpt="some text", retrieval_score=0.9, rerank_score=0.8, source="vector")
    assert c.id == "1"
    assert c.title == "Test"
    assert c.retrieval_score == 0.9


def test_empty_pipeline_returns_context():
    pipeline = ModularRAGPipeline()
    ctx = asyncio.run(pipeline.run("hello"))
    assert ctx.query == "hello"
    assert ctx.answer == ""


def test_module_executes_when_enabled():
    DummyModule.activated = False
    mod = DummyModule(activate=True)
    pipeline = ModularRAGPipeline([mod])
    ctx = asyncio.run(pipeline.run("test"))
    assert ctx.metadata.get("dummy_ran") is True
    assert "dummy" in ctx.metadata.get("activated_modules", [])


def test_module_skipped_when_disabled():
    mod = DisabledModule()
    pipeline = ModularRAGPipeline([mod])
    ctx = asyncio.run(pipeline.run("test"))
    assert "disabled_ran" not in ctx.metadata
    assert "disabled" in ctx.metadata.get("skipped_modules", [])


def test_module_skipped_when_should_activate_false():
    mod = DummyModule(activate=False)
    pipeline = ModularRAGPipeline([mod])
    ctx = asyncio.run(pipeline.run("test"))
    assert "dummy_ran" not in ctx.metadata
    assert "dummy" in ctx.metadata.get("skipped_modules", [])


def test_pipeline_tracks_timings():
    mod = DummyModule(activate=True)
    pipeline = ModularRAGPipeline([mod])
    ctx = asyncio.run(pipeline.run("test"))
    assert "dummy" in ctx.metadata.get("module_timings", {})
