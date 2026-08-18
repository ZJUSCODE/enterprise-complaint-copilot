from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.document.parsers.base import DocumentSection

logger = logging.getLogger(__name__)


@dataclass
class QualityScore:
    """Quality assessment for a document section."""
    completeness: float = 0.0
    readability: float = 0.0
    information_density: float = 0.0
    overall: float = 0.0
    issues: list[str] = field(default_factory=list)


@dataclass
class ConflictRecord:
    """Record of conflicting information between sections."""
    chunk_a_id: str = ""
    chunk_b_id: str = ""
    conflict_type: str = "contradiction"  # contradiction / outdated / ambiguous
    description: str = ""
    severity: str = "low"  # low / medium / high


class DataCleaner:
    """Enterprise-level data cleaning pipeline for document sections."""

    # Common noise patterns in enterprise documents
    NOISE_PATTERNS = [
        r"^第\s*\d+\s*页\s*$",
        r"^Page\s+\d+\s*$",
        r"^-{3,}$",
        r"^\*{3,}$",
        r"^={3,}$",
        r"^版权所有.*$",
        r"^Copyright.*$",
        r"^Confidential.*$",
        r"^机密.*$",
        r"^仅供内部.*$",
    ]

    def __init__(self, dedup_threshold: float = 0.95):
        self.dedup_threshold = dedup_threshold
        self._seen_hashes: set[str] = set()

    def clean(self, sections: list[DocumentSection]) -> list[DocumentSection]:
        """Run full cleaning pipeline on sections."""
        if not sections:
            return []

        cleaned = []
        for section in sections:
            # Step 1: Noise removal
            content = self._remove_noise(section.content)
            if not content.strip():
                continue
            section.content = content

            # Step 2: Deduplication
            content_hash = self._hash(section.content)
            if content_hash in self._seen_hashes:
                logger.debug("Duplicate section removed: %s", section.title[:30])
                continue
            self._seen_hashes.add(content_hash)

            # Step 3: Quality scoring
            quality = self._score_quality(section)
            section.metadata["quality_score"] = quality.overall
            section.metadata["quality_issues"] = quality.issues

            cleaned.append(section)

        # Step 4: Conflict detection
        conflicts = self._detect_conflicts(cleaned)
        if conflicts:
            logger.info("Detected %d potential conflicts", len(conflicts))
            for section in cleaned:
                section.metadata.setdefault("conflicts", [])

        return cleaned

    def _remove_noise(self, text: str) -> str:
        """Remove headers, footers, watermarks, boilerplate."""
        lines = text.split("\n")
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            # Check noise patterns
            is_noise = False
            for pattern in self.NOISE_PATTERNS:
                if re.match(pattern, stripped, re.IGNORECASE):
                    is_noise = True
                    break
            if not is_noise:
                cleaned_lines.append(line)
        return "\n".join(cleaned_lines)

    def _hash(self, content: str) -> str:
        """Generate content hash for deduplication."""
        normalized = re.sub(r"\s+", " ", content.strip().lower())
        return hashlib.md5(normalized.encode("utf-8")).hexdigest()

    def _score_quality(self, section: DocumentSection) -> QualityScore:
        """Score section quality on multiple dimensions."""
        content = section.content
        issues = []

        # Completeness: based on content length
        length = len(content)
        if length < 20:
            completeness = 0.2
            issues.append("内容过短")
        elif length < 100:
            completeness = 0.5
        elif length < 500:
            completeness = 0.8
        else:
            completeness = 1.0

        # Readability: sentence structure, punctuation
        sentences = re.split(r"[。！？.!?]", content)
        sentences = [s.strip() for s in sentences if s.strip()]
        avg_sentence_len = sum(len(s) for s in sentences) / max(len(sentences), 1)
        if avg_sentence_len > 200:
            readability = 0.3
            issues.append("句子过长")
        elif avg_sentence_len > 100:
            readability = 0.6
        else:
            readability = 1.0

        # Information density: ratio of meaningful characters
        chinese_chars = len(re.findall(r"[一-鿿]", content))
        alpha_chars = len(re.findall(r"[a-zA-Z]", content))
        total_chars = max(len(content), 1)
        density = (chinese_chars + alpha_chars) / total_chars
        if density < 0.3:
            information_density = 0.3
            issues.append("信息密度低")
        elif density < 0.6:
            information_density = 0.6
        else:
            information_density = min(density * 1.2, 1.0)

        # Overall: weighted average
        overall = completeness * 0.3 + readability * 0.3 + information_density * 0.4

        return QualityScore(
            completeness=round(completeness, 3),
            readability=round(readability, 3),
            information_density=round(information_density, 3),
            overall=round(overall, 3),
            issues=issues,
        )

    def _detect_conflicts(self, sections: list[DocumentSection]) -> list[ConflictRecord]:
        """Detect contradictory information across sections."""
        conflicts: list[ConflictRecord] = []
        # Simple keyword-based conflict detection
        conflict_keywords = [
            ("可以", "不可以"),
            ("允许", "禁止"),
            ("需要", "不需要"),
            ("必须", "不必"),
            ("支持", "不支持"),
        ]

        for i, a in enumerate(sections):
            for j, b in enumerate(sections):
                if j <= i:
                    continue
                for pos, neg in conflict_keywords:
                    if pos in a.content and neg in b.content:
                        # Check if they're about the same topic
                        a_words = set(re.findall(r"[一-鿿]{2,}", a.content[:200]))
                        b_words = set(re.findall(r"[一-鿿]{2,}", b.content[:200]))
                        overlap = a_words & b_words
                        if len(overlap) >= 2:
                            conflicts.append(ConflictRecord(
                                chunk_a_id=a.metadata.get("doc_id", f"section_{i}"),
                                chunk_b_id=b.metadata.get("doc_id", f"section_{j}"),
                                conflict_type="contradiction",
                                description=f"可能存在矛盾: '{pos}' vs '{neg}', 共同关键词: {', '.join(list(overlap)[:3])}",
                                severity="medium",
                            ))
        return conflicts

    def reset(self) -> None:
        """Reset deduplication state."""
        self._seen_hashes.clear()
