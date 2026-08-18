from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AuditEvent:
    """An audit log event."""
    event_id: str = ""
    timestamp: str = ""
    category: str = ""  # document / query / system / sensitive
    action: str = ""
    actor: str = ""  # user_id or "system"
    target: str = ""  # file path, chunk id, etc.
    details: dict[str, Any] = field(default_factory=dict)
    ip_address: str | None = None
    session_id: str | None = None
    result: str = "success"  # success / failure / blocked


class AuditLogger:
    """Enterprise audit logging for all operations."""

    VALID_CATEGORIES = {"document", "query", "system", "sensitive"}

    def __init__(self, db_path: str | Path, retention_days: int = 90):
        self.db_path = Path(db_path)
        self.retention_days = retention_days
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS document_audit_log (
                    event_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    target TEXT,
                    details TEXT,
                    ip_address TEXT,
                    session_id TEXT,
                    result TEXT DEFAULT 'success'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_audit_category ON document_audit_log(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_audit_timestamp ON document_audit_log(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_audit_actor ON document_audit_log(actor)")

    def log(
        self,
        category: str,
        action: str,
        actor: str = "system",
        target: str = "",
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        session_id: str | None = None,
        result: str = "success",
    ) -> AuditEvent:
        """Record an audit event."""
        if category not in self.VALID_CATEGORIES:
            logger.warning("Invalid audit category: %s, defaulting to 'system'", category)
            category = "system"

        event = AuditEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            category=category,
            action=action,
            actor=actor,
            target=target,
            details=details or {},
            ip_address=ip_address,
            session_id=session_id,
            result=result,
        )

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO document_audit_log (event_id, timestamp, category, action, actor, target, details, ip_address, session_id, result) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event.event_id, event.timestamp, event.category, event.action, event.actor, event.target, json.dumps(event.details, ensure_ascii=False), event.ip_address, event.session_id, event.result),
            )

        return event

    def query(
        self,
        category: str | None = None,
        action: str | None = None,
        actor: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: int = 50,
    ) -> list[AuditEvent]:
        """Query audit events with filters."""
        conditions = []
        params = []
        if category:
            conditions.append("category = ?")
            params.append(category)
        if action:
            conditions.append("action = ?")
            params.append(action)
        if actor:
            conditions.append("actor = ?")
            params.append(actor)
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM document_audit_log {where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()

        return [AuditEvent(
            event_id=row["event_id"],
            timestamp=row["timestamp"],
            category=row["category"],
            action=row["action"],
            actor=row["actor"],
            target=row["target"],
            details=json.loads(row["details"]) if row["details"] else {},
            ip_address=row["ip_address"],
            session_id=row["session_id"],
            result=row["result"],
        ) for row in rows]

    def stats(self) -> dict[str, Any]:
        """Get audit statistics."""
        with sqlite3.connect(str(self.db_path)) as conn:
            total = conn.execute("SELECT COUNT(*) FROM document_audit_log").fetchone()[0]
            by_category = dict(conn.execute("SELECT category, COUNT(*) FROM document_audit_log GROUP BY category").fetchall())
            by_result = dict(conn.execute("SELECT result, COUNT(*) FROM document_audit_log GROUP BY result").fetchall())
            recent_24h = conn.execute(
                "SELECT COUNT(*) FROM document_audit_log WHERE timestamp >= ?",
                ((datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(),),
            ).fetchone()[0]

        return {
            "total_events": total,
            "by_category": by_category,
            "by_result": by_result,
            "recent_24h": recent_24h,
            "retention_days": self.retention_days,
        }

    def cleanup(self) -> int:
        """Remove events older than retention period."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.retention_days)).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute("DELETE FROM document_audit_log WHERE timestamp < ?", (cutoff,))
            deleted = cursor.rowcount
        if deleted > 0:
            logger.info("Cleaned up %d old audit events", deleted)
        return deleted
