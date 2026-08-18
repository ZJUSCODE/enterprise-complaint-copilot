"""Tests for VersionManager."""
from __future__ import annotations

import tempfile
from pathlib import Path

from app.document.version import VersionManager


class TestVersionManager:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test.db"
        self.snapshots_dir = Path(self.tmpdir) / "snapshots"
        self.vm = VersionManager(self.db_path, self.snapshots_dir)

    def test_create_version(self):
        chunks = [{"id": "c1", "text": "hello"}, {"id": "c2", "text": "world"}]
        record = self.vm.create_version("main", "Initial", "test_user", chunks)
        assert record.version_id.startswith("v_")
        assert record.branch == "main"
        assert record.chunk_count == 2
        assert record.author == "test_user"

    def test_list_versions(self):
        self.vm.create_version("main", "V1", "user", [{"id": "c1", "text": "a"}])
        self.vm.create_version("main", "V2", "user", [{"id": "c2", "text": "b"}])
        versions = self.vm.list_versions()
        assert len(versions) == 2

    def test_list_versions_by_branch(self):
        self.vm.create_version("main", "V1", "user", [{"id": "c1", "text": "a"}])
        self.vm.create_version("staging", "V2", "user", [{"id": "c2", "text": "b"}])
        main_versions = self.vm.list_versions(branch="main")
        assert len(main_versions) == 1
        assert main_versions[0].branch == "main"

    def test_get_version(self):
        chunks = [{"id": "c1", "text": "hello"}]
        record = self.vm.create_version("main", "Test", "user", chunks)
        retrieved = self.vm.get_version(record.version_id)
        assert retrieved is not None
        assert retrieved.version_id == record.version_id

    def test_load_chunks(self):
        chunks = [{"id": "c1", "text": "hello"}, {"id": "c2", "text": "world"}]
        record = self.vm.create_version("main", "Test", "user", chunks)
        loaded = self.vm.load_chunks(record.version_id)
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0]["id"] == "c1"

    def test_diff(self):
        v1 = self.vm.create_version("main", "V1", "user", [{"id": "c1", "text": "a"}, {"id": "c2", "text": "b"}])
        v2 = self.vm.create_version("main", "V2", "user", [{"id": "c2", "text": "b"}, {"id": "c3", "text": "c"}])
        diff = self.vm.diff(v1.version_id, v2.version_id)
        assert "c3" in diff["added"]
        assert "c1" in diff["removed"]
        assert "c2" in diff["common"]

    def test_rollback(self):
        v1 = self.vm.create_version("main", "V1", "user", [{"id": "c1", "text": "a"}])
        self.vm.create_version("main", "V2", "user", [{"id": "c2", "text": "b"}])
        chunks = self.vm.rollback(v1.version_id)
        assert chunks is not None
        assert len(chunks) == 1
        assert chunks[0]["id"] == "c1"

    def test_rollback_nonexistent(self):
        result = self.vm.rollback("nonexistent")
        assert result is None
