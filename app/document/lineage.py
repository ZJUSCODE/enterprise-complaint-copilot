from __future__ import annotations

import logging
import sqlite3
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ProcessingStep:
    """A single processing step in the lineage."""
    step_name: str = ""  # parse / clean / chunk / embed / index
    timestamp: str = ""
    input_hash: str = ""
    output_hash: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


@dataclass
class LineageRecord:
    """Full lineage for a chunk from source to index."""
    chunk_id: str = ""
    source_file: str = ""
    source_page: int | None = None
    source_section: str = ""
    processing_steps: list[ProcessingStep] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    version_id: str = ""


class LineageTracker:
    """Tracks chunk-level processing lineage."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunk_lineage (
                    chunk_id TEXT PRIMARY KEY,
                    source_file TEXT,
                    source_page INTEGER,
                    source_section TEXT,
                    processing_steps TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    version_id TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lineage_source ON chunk_lineage(source_file)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_lineage_version ON chunk_lineage(version_id)")

    def record(
        self,
        chunk_id: str,
        source_file: str,
        source_page: int | None = None,
        source_section: str = "",
        version_id: str = "",
    ) -> None:
        """Record a new chunk's lineage."""
        now = datetime.now(timezone.utc).isoformat()
        steps = [ProcessingStep(step_name="parse", timestamp=now).to_dict()]
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO chunk_lineage (chunk_id, source_file, source_page, source_section, processing_steps, created_at, updated_at, version_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (chunk_id, source_file, source_page, source_section, json.dumps(steps), now, now, version_id),
            )

    def add_step(self, chunk_id: str, step_name: str, duration_ms: float = 0.0, parameters: dict[str, Any] | None = None) -> None:
        """Add a processing step to an existing chunk's lineage."""
        import hashlib
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT processing_steps FROM chunk_lineage WHERE chunk_id = ?", (chunk_id,)).fetchone()
            if not row:
                return
            steps = json.loads(row["processing_steps"])
            steps.append(ProcessingStep(
                step_name=step_name,
                timestamp=now,
                parameters=parameters or {},
                duration_ms=duration_ms,
            ).to_dict())
            conn.execute(
                "UPDATE chunk_lineage SET processing_steps = ?, updated_at = ? WHERE chunk_id = ?",
                (json.dumps(steps), now, chunk_id),
            )

    def get_lineage(self, chunk_id: str) -> LineageRecord | None:
        """Get full lineage for a chunk."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM chunk_lineage WHERE chunk_id = ?", (chunk_id,)).fetchone()
        if not row:
            return None
        return LineageRecord(
            chunk_id=row["chunk_id"],
            source_file=row["source_file"],
            source_page=row["source_page"],
            source_section=row["source_section"],
            processing_steps=[ProcessingStep(**s) for s in json.loads(row["processing_steps"])],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            version_id=row["version_id"],
        )

    def get_chunks_from_file(self, file_path: str) -> list[str]:
        """Get all chunk IDs from a source file."""
        filename = Path(file_path).name
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT chunk_id FROM chunk_lineage WHERE source_file = ?", (filename,)).fetchall()
        return [row[0] for row in rows]

    def get_chunks_by_step(self, step_name: str) -> list[str]:
        """Get all chunk IDs that were processed by a specific step."""
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT chunk_id, processing_steps FROM chunk_lineage").fetchall()
        result = []
        for chunk_id, steps_json in rows:
            steps = json.loads(steps_json)
            if any(s.get("step_name") == step_name for s in steps):
                result.append(chunk_id)
        return result

    def trace_back(self, chunk_id: str, step_name: str) -> dict[str, Any] | None:
        """Get state at a specific processing step."""
        lineage = self.get_lineage(chunk_id)
        if not lineage:
            return None
        for step in lineage.processing_steps:
            if step.step_name == step_name:
                return asdict(step)
        return None


# Patch ProcessingStep to have a to_dict method
def _processing_step_to_dict(self) -> dict[str, Any]:
    return {
        "step_name": self.step_name,
        "timestamp": self.timestamp,
        "input_hash": self.input_hash,
        "output_hash": self.output_hash,
        "parameters": self.parameters,
        "duration_ms": self.duration_ms,
    }

ProcessingStep.to_dict = _processing_step_to_dict
