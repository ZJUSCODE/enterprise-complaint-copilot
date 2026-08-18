"""Tests for DataCleaner."""
from __future__ import annotations

from app.document.cleaner import DataCleaner, QualityScore, ConflictRecord
from app.document.parsers.base import DocumentSection


class TestDataCleaner:
    def test_clean_empty(self):
        cleaner = DataCleaner()
        assert cleaner.clean([]) == []

    def test_deduplication(self):
        cleaner = DataCleaner()
        sections = [
            DocumentSection(content="这是重复的内容。"),
            DocumentSection(content="这是重复的内容。"),
            DocumentSection(content="这是不同的内容。"),
        ]
        result = cleaner.clean(sections)
        assert len(result) == 2

    def test_noise_removal(self):
        cleaner = DataCleaner()
        sections = [
            DocumentSection(content="第 1 页\n这是正文内容。\n版权所有 2024"),
        ]
        result = cleaner.clean(sections)
        assert len(result) == 1
        assert "第 1 页" not in result[0].content
        assert "版权所有" not in result[0].content
        assert "正文内容" in result[0].content

    def test_quality_scoring(self):
        cleaner = DataCleaner()
        sections = [
            DocumentSection(content="短"),
            DocumentSection(content="这是一段较长的内容，包含足够的信息来获得合理的质量评分。" * 5),
        ]
        result = cleaner.clean(sections)
        assert len(result) == 2
        # Short content should have lower quality
        assert result[0].metadata["quality_score"] < result[1].metadata["quality_score"]

    def test_conflict_detection(self):
        cleaner = DataCleaner()
        sections = [
            DocumentSection(content="退货政策：生鲜商品可以退货，需要提供照片。", metadata={"doc_id": "a"}),
            DocumentSection(content="退货政策：生鲜商品不可以退货，因为易腐烂。", metadata={"doc_id": "b"}),
        ]
        # Conflict detection runs but doesn't remove sections
        result = cleaner.clean(sections)
        assert len(result) == 2

    def test_reset(self):
        cleaner = DataCleaner()
        sections = [DocumentSection(content="测试内容。")]
        cleaner.clean(sections)
        assert len(cleaner._seen_hashes) == 1
        cleaner.reset()
        assert len(cleaner._seen_hashes) == 0


class TestQualityScore:
    def test_defaults(self):
        qs = QualityScore()
        assert qs.completeness == 0.0
        assert qs.overall == 0.0
        assert qs.issues == []


class TestConflictRecord:
    def test_defaults(self):
        cr = ConflictRecord()
        assert cr.conflict_type == "contradiction"
        assert cr.severity == "low"
