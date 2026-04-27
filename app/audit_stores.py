from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any


class AuditLogStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_database()

    def _ensure_database(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    trace_id TEXT,
                    session_id TEXT,
                    mode TEXT NOT NULL,
                    route_mode TEXT,
                    route_source TEXT,
                    route_confidence REAL,
                    route_reason TEXT,
                    blocked_by_guardrail INTEGER NOT NULL DEFAULT 0,
                    blocked_by_permission INTEGER NOT NULL DEFAULT 0,
                    user_role TEXT NOT NULL DEFAULT 'analyst',
                    user_message TEXT NOT NULL,
                    response_title TEXT,
                    tool_trace_json TEXT NOT NULL,
                    sql_preview TEXT,
                    latency_ms REAL NOT NULL,
                    token_usage_json TEXT NOT NULL DEFAULT '{}',
                    estimated_cost_usd REAL NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_events(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_events(request_id)")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_events)").fetchall()}
            if "blocked_by_permission" not in columns:
                conn.execute("ALTER TABLE audit_events ADD COLUMN blocked_by_permission INTEGER NOT NULL DEFAULT 0")
            if "user_role" not in columns:
                conn.execute("ALTER TABLE audit_events ADD COLUMN user_role TEXT NOT NULL DEFAULT 'analyst'")
            if "trace_id" not in columns:
                conn.execute("ALTER TABLE audit_events ADD COLUMN trace_id TEXT")
            if "token_usage_json" not in columns:
                conn.execute("ALTER TABLE audit_events ADD COLUMN token_usage_json TEXT NOT NULL DEFAULT '{}'")
            if "estimated_cost_usd" not in columns:
                conn.execute("ALTER TABLE audit_events ADD COLUMN estimated_cost_usd REAL NOT NULL DEFAULT 0")
            if "retry_count" not in columns:
                conn.execute("ALTER TABLE audit_events ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
            conn.commit()

    def record(self, event: dict[str, Any]) -> None:
        route = event.get("route") or {}
        tool_trace = event.get("tool_trace") or []
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    request_id, trace_id, session_id, mode, route_mode, route_source, route_confidence,
                    route_reason, blocked_by_guardrail, blocked_by_permission, user_role, user_message, response_title,
                    tool_trace_json, sql_preview, latency_ms, token_usage_json, estimated_cost_usd, retry_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["request_id"],
                    event.get("trace_id"),
                    event.get("session_id"),
                    event["mode"],
                    route.get("mode"),
                    route.get("source"),
                    route.get("confidence"),
                    route.get("reason"),
                    1 if event.get("blocked_by_guardrail") else 0,
                    1 if event.get("blocked_by_permission") else 0,
                    event.get("user_role", "analyst"),
                    event["user_message"],
                    event.get("response_title"),
                    json.dumps(tool_trace, ensure_ascii=False),
                    event.get("sql_preview"),
                    float(event.get("latency_ms", 0)),
                    json.dumps(event.get("token_usage") or {}, ensure_ascii=False),
                    float(event.get("estimated_cost_usd", 0)),
                    int(event.get("retry_count", 0) or 0),
                ),
            )
            conn.commit()

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT request_id, trace_id, session_id, mode, route_mode, route_source, route_confidence,
                       route_reason, blocked_by_guardrail, blocked_by_permission, user_role, user_message, response_title,
                       tool_trace_json, sql_preview, latency_ms, token_usage_json, estimated_cost_usd, retry_count, created_at
                FROM audit_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            item["blocked_by_guardrail"] = bool(item["blocked_by_guardrail"])
            item["blocked_by_permission"] = bool(item["blocked_by_permission"])
            item["tool_trace"] = json.loads(item.pop("tool_trace_json") or "[]")
            item["token_usage"] = json.loads(item.pop("token_usage_json") or "{}")
            events.append(item)
        return events


class HumanReviewQueue:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_database()

    def _ensure_database(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS human_review_queue (
                    case_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    session_id TEXT,
                    user_role TEXT NOT NULL DEFAULT 'analyst',
                    source_mode TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    response_summary TEXT,
                    tool_trace_json TEXT NOT NULL,
                    case_priority TEXT NOT NULL DEFAULT 'medium',
                    escalation_reason TEXT,
                    assignee TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewer_note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_review_status ON human_review_queue(status, created_at)")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(human_review_queue)").fetchall()}
            if "case_priority" not in columns:
                conn.execute("ALTER TABLE human_review_queue ADD COLUMN case_priority TEXT NOT NULL DEFAULT 'medium'")
            if "escalation_reason" not in columns:
                conn.execute("ALTER TABLE human_review_queue ADD COLUMN escalation_reason TEXT")
            if "assignee" not in columns:
                conn.execute("ALTER TABLE human_review_queue ADD COLUMN assignee TEXT")
            conn.commit()

    def enqueue(self, event: dict[str, Any]) -> dict[str, Any]:
        case_id = event.get("case_id") or f"REV-{uuid.uuid4().hex[:10].upper()}"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT OR IGNORE INTO human_review_queue (
                    case_id, request_id, session_id, user_role, source_mode, reason,
                    user_message, response_summary, tool_trace_json, case_priority, escalation_reason, assignee
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    event["request_id"],
                    event.get("session_id"),
                    event.get("user_role", "analyst"),
                    event.get("source_mode", "unknown"),
                    event.get("reason", "需要人工复核"),
                    event.get("user_message", ""),
                    event.get("response_summary"),
                    json.dumps(event.get("tool_trace") or [], ensure_ascii=False),
                    event.get("case_priority", "medium"),
                    event.get("escalation_reason") or event.get("reason"),
                    event.get("assignee"),
                ),
            )
            row = conn.execute(
                """
                SELECT case_id, request_id, session_id, user_role, source_mode, reason,
                       user_message, response_summary, case_priority, escalation_reason, assignee, status, created_at, updated_at
                FROM human_review_queue
                WHERE request_id = ?
                """,
                (event["request_id"],),
            ).fetchone()
            conn.commit()
        return dict(row) if row else {"case_id": case_id, "request_id": event["request_id"], "status": "pending"}

    def recent(self, limit: int = 20, status: str = "pending") -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT case_id, request_id, session_id, user_role, source_mode, reason,
                       user_message, response_summary, tool_trace_json, case_priority, escalation_reason, assignee, status,
                       reviewer_note, created_at, updated_at
                FROM human_review_queue
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["tool_trace"] = json.loads(item.pop("tool_trace_json") or "[]")
            items.append(item)
        return items

    def update_status(self, case_id: str, status: str, reviewer_note: str | None = None, assignee: str | None = None, case_priority: str | None = None) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE human_review_queue
                SET status = ?,
                    reviewer_note = ?,
                    assignee = COALESCE(?, assignee),
                    case_priority = COALESCE(?, case_priority),
                    updated_at = CURRENT_TIMESTAMP
                WHERE case_id = ?
                """,
                (status, reviewer_note, assignee, case_priority, case_id),
            )
            row = conn.execute(
                """
                SELECT case_id, request_id, session_id, user_role, source_mode, reason,
                       user_message, response_summary, tool_trace_json, case_priority, escalation_reason, assignee, status,
                       reviewer_note, created_at, updated_at
                FROM human_review_queue
                WHERE case_id = ?
                """,
                (case_id,),
            ).fetchone()
            conn.commit()
        if not row:
            return None
        item = dict(row)
        item["tool_trace"] = json.loads(item.pop("tool_trace_json") or "[]")
        return item


class FeedbackEventStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_database()

    def _ensure_database(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback_events (
                    event_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    session_id TEXT,
                    rating TEXT NOT NULL CHECK (rating IN ('up', 'down')),
                    comment TEXT,
                    user_role TEXT NOT NULL DEFAULT 'analyst',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_request ON feedback_events(request_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback_events(created_at)")
            conn.commit()

    def record(self, event: dict[str, Any]) -> dict[str, Any]:
        event_id = event.get("event_id") or f"FB-{uuid.uuid4().hex[:10].upper()}"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO feedback_events (
                    event_id, request_id, session_id, rating, comment, user_role
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event["request_id"],
                    event.get("session_id"),
                    event["rating"],
                    event.get("comment"),
                    event.get("user_role", "analyst"),
                ),
            )
            row = conn.execute(
                """
                SELECT event_id, request_id, session_id, rating, comment, user_role, created_at
                FROM feedback_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            conn.commit()
        return dict(row)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT event_id, request_id, session_id, rating, comment, user_role, created_at
                FROM feedback_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
