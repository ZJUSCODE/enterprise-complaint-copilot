"""Tests for LineageTracker."""
from __future__ import annotations

import tempfile
from pathlib import Path

from app.document.lineage import LineageTracker


class TestLineageTracker:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test.db"
        self.tracker = LineageTracker(self.db_path)

    def test_record_and_get(self):
        self.tracker.record("chunk_001", "test.md", source_page=1, source_section="Section A")
        lineage = self.tracker.get_lineage("chunk_001")
        assert lineage is not None
        assert lineage.chunk_id == "chunk_001"
        assert lineage.source_file == "test.md"
        assert lineage.source_page == 1
        assert lineage.source_section == "Section A"
        assert len(lineage.processing_steps) == 1
        assert lineage.processing_steps[0].step_name == "parse"

    def test_add_step(self):
        self.tracker.record("chunk_002", "test.md")
        self.tracker.add_step("chunk_002", "clean", duration_ms=15.5)
        self.tracker.add_step("chunk_002", "chunk", duration_ms=5.0)
        lineage = self.tracker.get_lineage("chunk_002")
        assert lineage is not None
        assert len(lineage.processing_steps) == 3  # parse + clean + chunk
        assert lineage.processing_steps[1].step_name == "clean"
        assert lineage.processing_steps[1].duration_ms == 15.5

    def test_get_chunks_from_file(self):
        self.tracker.record("c1", "doc_a.md")
        self.tracker.record("c2", "doc_a.md")
        self.tracker.record("c3", "doc_b.md")
        chunks = self.tracker.get_chunks_from_file("doc_a.md")
        assert len(chunks) == 2
        assert "c1" in chunks
        assert "c2" in chunks

    def test_get_lineage_nonexistent(self):
        assert self.tracker.get_lineage("nonexistent") is None

    def test_trace_back(self):
        self.tracker.record("chunk_003", "test.md")
        self.tracker.add_step("chunk_003", "clean")
        step = self.tracker.trace_back("chunk_003", "clean")
        assert step is not None
        assert step["step_name"] == "clean"

    def test_trace_back_nonexistent_step(self):
        self.tracker.record("chunk_004", "test.md")
        assert self.tracker.trace_back("chunk_004", "embed") is None
