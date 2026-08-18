from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class VersionRecord:
    """A knowledge base version snapshot."""
    version_id: str
    branch: str
    parent_id: str | None
    timestamp: str
    message: str
    author: str
    chunk_count: int
    added: int
    removed: int
    modified: int
    snapshot_path: str


class VersionManager:
    """Git-level version management for the knowledge base."""

    def __init__(self, db_path: str | Path, snapshots_dir: str | Path):
        self.db_path = Path(db_path)
        self.snapshots_dir = Path(snapshots_dir)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS kb_versions (
                    version_id TEXT PRIMARY KEY,
                    branch TEXT NOT NULL,
                    parent_id TEXT,
                    timestamp TEXT NOT NULL,
                    message TEXT,
                    author TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    added INTEGER DEFAULT 0,
                    removed INTEGER DEFAULT 0,
                    modified INTEGER DEFAULT 0,
                    snapshot_path TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_versions_branch ON kb_versions(branch)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_versions_timestamp ON kb_versions(timestamp)")

    def create_version(
        self,
        branch: str,
        message: str,
        author: str,
        chunks: list[dict[str, Any]],
        parent_id: str | None = None,
    ) -> VersionRecord:
        """Create a new version snapshot."""
        version_id = f"v_{uuid.uuid4().hex[:12]}"
        snapshot_path = self.snapshots_dir / version_id
        snapshot_path.mkdir(parents=True, exist_ok=True)

        # Save chunks to snapshot
        chunks_file = snapshot_path / "chunks.json"
        chunks_file.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")

        # Calculate diff if parent exists
        added = len(chunks)
        removed = 0
        modified = 0
        if parent_id:
            parent_chunks = self._load_snapshot(parent_id)
            if parent_chunks is not None:
                parent_ids = {c.get("id") for c in parent_chunks}
                current_ids = {c.get("id") for c in chunks}
                added = len(current_ids - parent_ids)
                removed = len(parent_ids - current_ids)
                modified = len(parent_ids & current_ids)  # simplified

        now = datetime.now(timezone.utc).isoformat()
        record = VersionRecord(
            version_id=version_id,
            branch=branch,
            parent_id=parent_id,
            timestamp=now,
            message=message,
            author=author,
            chunk_count=len(chunks),
            added=added,
            removed=removed,
            modified=modified,
            snapshot_path=str(snapshot_path),
        )

        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO kb_versions (version_id, branch, parent_id, timestamp, message, author, chunk_count, added, removed, modified, snapshot_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (record.version_id, record.branch, record.parent_id, record.timestamp, record.message, record.author, record.chunk_count, record.added, record.removed, record.modified, record.snapshot_path),
            )

        logger.info("Created version %s on branch %s (%d chunks)", version_id, branch, len(chunks))
        return record

    def list_versions(self, branch: str | None = None, limit: int = 20) -> list[VersionRecord]:
        """List versions, optionally filtered by branch."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            if branch:
                rows = conn.execute("SELECT * FROM kb_versions WHERE branch = ? ORDER BY timestamp DESC LIMIT ?", (branch, limit)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM kb_versions ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
        return [VersionRecord(**dict(row)) for row in rows]

    def get_version(self, version_id: str) -> VersionRecord | None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM kb_versions WHERE version_id = ?", (version_id,)).fetchone()
        return VersionRecord(**dict(row)) if row else None

    def load_chunks(self, version_id: str) -> list[dict[str, Any]] | None:
        """Load chunks from a version snapshot."""
        return self._load_snapshot(version_id)

    def diff(self, version_a: str, version_b: str) -> dict[str, Any]:
        """Compare two versions."""
        chunks_a = self._load_snapshot(version_a) or []
        chunks_b = self._load_snapshot(version_b) or []
        ids_a = {c.get("id") for c in chunks_a}
        ids_b = {c.get("id") for c in chunks_b}
        return {
            "version_a": version_a,
            "version_b": version_b,
            "added": list(ids_b - ids_a),
            "removed": list(ids_a - ids_b),
            "common": list(ids_a & ids_b),
            "added_count": len(ids_b - ids_a),
            "removed_count": len(ids_a - ids_b),
        }

    def rollback(self, version_id: str, author: str = "system") -> list[dict[str, Any]] | None:
        """Rollback to a specific version, returning its chunks."""
        chunks = self._load_snapshot(version_id)
        if chunks is None:
            return None
        record = self.get_version(version_id)
        if record:
            self.create_version(
                branch=record.branch,
                message=f"Rollback to {version_id}",
                author=author,
                chunks=chunks,
                parent_id=version_id,
            )
        return chunks

    def _load_snapshot(self, version_id: str) -> list[dict[str, Any]] | None:
        snapshot_path = self.snapshots_dir / version_id / "chunks.json"
        if not snapshot_path.exists():
            return None
        try:
            return json.loads(snapshot_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to load snapshot %s: %s", version_id, exc)
            return None
