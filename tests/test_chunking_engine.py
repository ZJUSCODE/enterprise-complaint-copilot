"""Tests for ChunkingEngine."""
from __future__ import annotations

from app.document.chunking import ChunkingEngine, Chunk, ChunkMetadata
from app.document.parsers.base import DocumentSection


class TestChunkingEngine:
    def test_heading_strategy(self):
        engine = ChunkingEngine(strategy="heading", max_chars=200)
        sections = [
            DocumentSection(title="标题一", content="第一段内容。", section_type="heading"),
            DocumentSection(title="标题一", content="这是正文内容，包含一些详细信息。", section_type="paragraph"),
            DocumentSection(title="标题二", content="第二段内容。", section_type="heading"),
        ]
        chunks = engine.chunk(sections, source_file="test.md", source_type=".md")
        assert len(chunks) >= 2
        assert all(c.metadata.source_file == "test.md" for c in chunks)
        assert all(c.metadata.source_type == ".md" for c in chunks)

    def test_fixed_strategy(self):
        engine = ChunkingEngine(strategy="fixed", max_chars=100, overlap=20)
        sections = [
            DocumentSection(content="A" * 250),
        ]
        chunks = engine.chunk(sections, source_file="test.txt")
        assert len(chunks) >= 2
        assert all(c.metadata.char_count <= 100 for c in chunks)

    def test_recursive_strategy(self):
        engine = ChunkingEngine(strategy="recursive", max_chars=100)
        sections = [
            DocumentSection(content="第一段。\n\n第二段。\n\n第三段。"),
        ]
        chunks = engine.chunk(sections)
        assert len(chunks) >= 1

    def test_small_to_top_strategy(self):
        engine = ChunkingEngine(strategy="small_to_top", max_chars=50)
        sections = [
            DocumentSection(title="章节", content="这是" * 30, section_type="paragraph"),
        ]
        chunks = engine.chunk(sections, source_file="test.md")
        # Should have parent + child chunks
        assert len(chunks) >= 2

    def test_empty_sections(self):
        engine = ChunkingEngine()
        assert engine.chunk([]) == []

    def test_large_section_sub_chunking(self):
        engine = ChunkingEngine(strategy="heading", max_chars=100)
        sections = [
            DocumentSection(
                title="大章节",
                content="这是一段很长的内容。" * 50,
                section_type="paragraph",
            ),
        ]
        chunks = engine.chunk(sections)
        assert len(chunks) >= 2
        assert all(c.metadata.char_count <= 200 for c in chunks)  # some tolerance


class TestChunkMetadata:
    def test_defaults(self):
        meta = ChunkMetadata()
        assert meta.chunk_id == ""
        assert meta.char_count == 0
        assert meta.quality_score == 0.0


class TestChunk:
    def test_defaults(self):
        chunk = Chunk()
        assert chunk.text == ""
        assert isinstance(chunk.metadata, ChunkMetadata)
