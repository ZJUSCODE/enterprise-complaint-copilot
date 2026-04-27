from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

try:
    import redis
except ImportError:  # pragma: no cover - optional production dependency
    redis = None

from app.config import Settings
from app.security import hash_password, utc_now, verify_password


class RedisRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.available = False
        self.error: str | None = None
        self.client: Any | None = None
        self.memory: dict[str, Any] = {}
        if not settings.redis_enabled:
            self.error = "redis_disabled"
            return
        if redis is None:
            self.error = "redis_package_missing"
            return
        try:
            self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=0.25, socket_timeout=0.25)
            self.client.ping()
            self.available = True
        except Exception as exc:
            self.client = None
            self.error = f"redis_unavailable:{exc}"

    def _memory_expired(self, key: str) -> bool:
        item = self.memory.get(key)
        if not isinstance(item, dict) or "expires_at" not in item:
            return False
        if item["expires_at"] and item["expires_at"] < time.time():
            self.memory.pop(key, None)
            return True
        return False

    def get(self, key: str) -> str | None:
        if self.available and self.client:
            return self.client.get(key)
        if self._memory_expired(key):
            return None
        item = self.memory.get(key)
        if isinstance(item, dict) and "value" in item:
            return item["value"]
        return item if isinstance(item, str) else None

    def setex(self, key: str, seconds: int, value: str) -> None:
        if self.available and self.client:
            self.client.setex(key, seconds, value)
            return
        self.memory[key] = {"value": value, "expires_at": time.time() + seconds if seconds else None}

    def get_json(self, key: str) -> Any | None:
        raw = self.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set_json(self, key: str, value: Any, seconds: int) -> None:
        self.setex(key, seconds, json.dumps(value, ensure_ascii=False))

    def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        if self.available and self.client:
            value = int(self.client.incr(key))
            if value == 1:
                self.client.expire(key, ttl_seconds)
            return value
        if self._memory_expired(key):
            self.memory.pop(key, None)
        item = self.memory.get(key)
        value = int(item.get("value", 0) if isinstance(item, dict) else 0) + 1
        self.memory[key] = {"value": str(value), "expires_at": time.time() + ttl_seconds}
        return value

    def push_event(self, key: str, payload: dict[str, Any], limit: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False)
        if self.available and self.client:
            self.client.lpush(key, raw)
            self.client.ltrim(key, 0, limit - 1)
            return
        events = self.memory.setdefault(key, [])
        if isinstance(events, list):
            events.insert(0, raw)
            del events[limit:]

    def list_events(self, key: str, limit: int = 50) -> list[dict[str, Any]]:
        if self.available and self.client:
            rows = self.client.lrange(key, 0, limit - 1)
        else:
            rows = self.memory.get(key, [])[:limit] if isinstance(self.memory.get(key), list) else []
        events = []
        for row in rows:
            try:
                events.append(json.loads(row))
            except json.JSONDecodeError:
                pass
        return events


class UserStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_database()

    def _ensure_database(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('viewer', 'analyst', 'supervisor')),
                    password_hash TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        self._seed_demo_users()

    def _seed_demo_users(self) -> None:
        demo_users = [
            ("viewer@example.com", "Viewer Demo", "viewer", "Viewer@123"),
            ("analyst@example.com", "Analyst Demo", "analyst", "Analyst@123"),
            ("supervisor@example.com", "Supervisor Demo", "supervisor", "Supervisor@123"),
        ]
        with sqlite3.connect(self.db_path) as conn:
            for username, display_name, role, password in demo_users:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO users (id, username, display_name, role, password_hash)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (f"usr_{uuid.uuid5(uuid.NAMESPACE_DNS, username).hex[:16]}", username, display_name, role, hash_password(password)),
                )
            conn.commit()

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, username, display_name, role, password_hash, is_active FROM users WHERE username = ?",
                (username.strip().lower(),),
            ).fetchone()
        if not row or not row["is_active"] or not verify_password(password, row["password_hash"]):
            return None
        item = dict(row)
        item.pop("password_hash", None)
        item["is_active"] = bool(item["is_active"])
        return item

    def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, username, display_name, role, is_active, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["is_active"] = bool(item["is_active"])
        return item


class TaskQueueStore:
    def __init__(self, redis_runtime: RedisRuntime):
        self.redis = redis_runtime

    def create(self, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = f"task_{uuid.uuid4().hex[:16]}"
        now = utc_now().isoformat()
        item = {"task_id": task_id, "task_type": task_type, "status": "queued", "payload": payload, "created_at": now, "updated_at": now}
        self.redis.set_json(f"task:{task_id}", item, 86400)
        self.redis.push_event("task_events", {"event": "queued", **item})
        return item

    def update(self, task_id: str, status: str, result: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
        item = self.get(task_id) or {"task_id": task_id, "task_type": "unknown", "payload": {}, "created_at": utc_now().isoformat()}
        item.update({"status": status, "result": result, "error": error, "updated_at": utc_now().isoformat()})
        self.redis.set_json(f"task:{task_id}", item, 86400)
        self.redis.push_event("task_events", {"event": status, **item})
        return item

    def get(self, task_id: str) -> dict[str, Any] | None:
        return self.redis.get_json(f"task:{task_id}")

    def events(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.redis.list_events("task_events", limit=limit)


class SessionMemoryStore:
    def __init__(self, redis_runtime: RedisRuntime | None = None, ttl_seconds: int = 86400):
        self.sessions: dict[str, list[dict[str, str]]] = {}
        self.redis = redis_runtime
        self.ttl_seconds = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}:messages"

    def get_or_create(self, session_id: str | None = None) -> str:
        sid = session_id or str(uuid.uuid4())
        if self.redis and self.redis.available:
            if self.redis.get_json(self._key(sid)) is None:
                self.redis.set_json(self._key(sid), [], self.ttl_seconds)
        else:
            self.sessions.setdefault(sid, [])
        return sid

    def recent_messages(self, session_id: str, limit: int = 6) -> list[dict[str, str]]:
        if self.redis and self.redis.available:
            return (self.redis.get_json(self._key(session_id)) or [])[-limit:]
        return self.sessions.get(session_id, [])[-limit:]

    def append(self, session_id: str, role: str, content: str) -> None:
        if self.redis and self.redis.available:
            messages = self.redis.get_json(self._key(session_id)) or []
            messages.append({"role": role, "content": content})
            self.redis.set_json(self._key(session_id), messages[-12:], self.ttl_seconds)
            return
        self.sessions.setdefault(session_id, []).append({"role": role, "content": content})
        self.sessions[session_id] = self.sessions[session_id][-12:]
