import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from app.modules.knowledge_updater import KnowledgeUpdater


def test_chunk_file_basic():
    updater = KnowledgeUpdater()
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", encoding="utf-8", delete=False) as f:
        f.write("# Test\n\n## Section 1\n\n这是测试内容。" * 20)
        f.flush()
        path = Path(f.name)

    chunks = updater._chunk_file(path)
    assert len(chunks) > 0
    assert all("id" in c for c in chunks)
    assert all("text" in c for c in chunks)
    assert all("metadata" in c for c in chunks)
    path.unlink()


def test_chunk_file_short():
    updater = KnowledgeUpdater()
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", encoding="utf-8", delete=False) as f:
        f.write("## Section\n\n短内容。")
        f.flush()
        path = Path(f.name)

    chunks = updater._chunk_file(path)
    assert len(chunks) == 1
    path.unlink()


def test_on_file_change_without_vector_store():
    """Should not crash when vector store is not configured."""
    updater = KnowledgeUpdater()
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", encoding="utf-8", delete=False) as f:
        f.write("## Section\n\n测试内容。")
        f.flush()
        path = Path(f.name)

    # Should not raise
    updater.on_file_change(path)
    path.unlink()


def test_on_file_delete_without_vector_store():
    """Should not crash when vector store is not configured."""
    updater = KnowledgeUpdater()
    updater.on_file_delete(Path("nonexistent.md"))


def test_stop_watching_without_start():
    """Should not crash when called without starting."""
    updater = KnowledgeUpdater()
    updater.stop_watching()
