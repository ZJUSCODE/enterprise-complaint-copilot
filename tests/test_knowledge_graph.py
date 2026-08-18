import pytest
import asyncio
import tempfile
from pathlib import Path
from app.modules.base import RAGContext
from app.modules.knowledge_graph import extract_triples, KnowledgeGraphRetriever


def test_extract_triples_causal():
    text = "生鲜退货导致冷链断裂"
    triples = extract_triples(text)
    assert len(triples) >= 1
    assert any("生鲜退货" in t[0] and "冷链断裂" in t[2] for t in triples)


def test_extract_triples_requirement():
    text = "高货值商品需要主管复核"
    triples = extract_triples(text)
    assert len(triples) >= 1
    assert any("高货值商品" in t[0] for t in triples)


def test_extract_triples_if_then():
    text = "如果超过100元则需要人工审核"
    triples = extract_triples(text)
    assert len(triples) >= 1


def test_extract_triples_empty():
    text = "这是一段普通文本"
    triples = extract_triples(text)
    # May or may not find triples, but shouldn't crash
    assert isinstance(triples, list)


def test_kg_builds_from_markdown():
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_dir = Path(tmpdir)
        sop = kb_dir / "test_sop.md"
        sop.write_text("# 测试SOP\n\n## 退款流程\n\n生鲜退货导致冷链断裂，需要主管复核。高货值商品需要人工审核。", encoding="utf-8")

        kg = KnowledgeGraphRetriever(kb_dir)
        assert kg.graph.number_of_nodes() > 0
        assert kg.graph.number_of_edges() > 0


def test_kg_retrieval_finds_entities():
    with tempfile.TemporaryDirectory() as tmpdir:
        kb_dir = Path(tmpdir)
        sop = kb_dir / "test_sop.md"
        sop.write_text("# 测试SOP\n\n## 退款流程\n\n生鲜退货导致冷链断裂。高货值商品需要主管复核。", encoding="utf-8")

        kg = KnowledgeGraphRetriever(kb_dir)
        ctx = asyncio.run(kg.execute(RAGContext(query="生鲜退货为什么会导致冷链断裂", retrieval_strategy="hybrid_with_kg")))
        assert len(ctx.kg_results) > 0
        assert ctx.metadata["kg_retriever"]["entities_found"]


def test_kg_skips_without_kg_strategy():
    kg = KnowledgeGraphRetriever()
    ctx = RAGContext(query="test", retrieval_strategy="hybrid")
    assert kg.should_activate(ctx) is False


def test_kg_activates_with_kg_strategy():
    kg = KnowledgeGraphRetriever()
    ctx = RAGContext(query="test", retrieval_strategy="hybrid_with_kg")
    assert kg.should_activate(ctx) is True
