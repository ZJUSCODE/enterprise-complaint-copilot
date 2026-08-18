"""Tests for AuditLogger."""
from __future__ import annotations

import tempfile
from pathlib import Path

from app.document.audit import AuditLogger


class TestAuditLogger:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = Path(self.tmpdir) / "test.db"
        self.logger = AuditLogger(self.db_path)

    def test_log_event(self):
        event = self.logger.log("document", "upload", actor="admin", target="test.pdf")
        assert event.event_id.startswith("evt_")
        assert event.category == "document"
        assert event.action == "upload"
        assert event.actor == "admin"
        assert event.result == "success"

    def test_query_by_category(self):
        self.logger.log("document", "upload", actor="admin")
        self.logger.log("query", "search", actor="user")
        self.logger.log("system", "cleanup", actor="system")
        results = self.logger.query(category="document")
        assert len(results) == 1
        assert results[0].category == "document"

    def test_query_by_action(self):
        self.logger.log("document", "upload", actor="admin")
        self.logger.log("document", "delete", actor="admin")
        results = self.logger.query(action="upload")
        assert len(results) == 1

    def test_query_by_actor(self):
        self.logger.log("document", "upload", actor="admin")
        self.logger.log("document", "upload", actor="user")
        results = self.logger.query(actor="admin")
        assert len(results) == 1

    def test_stats(self):
        self.logger.log("document", "upload")
        self.logger.log("query", "search")
        self.logger.log("document", "delete")
        stats = self.logger.stats()
        assert stats["total_events"] == 3
        assert stats["by_category"]["document"] == 2
        assert stats["by_category"]["query"] == 1

    def test_invalid_category_defaults_to_system(self):
        event = self.logger.log("invalid", "test")
        assert event.category == "system"

    def test_cleanup(self):
        self.logger.log("document", "upload")
        # With default 90-day retention, nothing should be cleaned
        deleted = self.logger.cleanup()
        assert deleted == 0
