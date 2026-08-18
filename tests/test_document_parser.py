"""Tests for document parsers."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.document.parsers.base import DocumentSection
from app.document.parser import DocumentParser


class TestDocumentParser:
    def test_supported_extensions(self):
        parser = DocumentParser()
        exts = parser.supported_extensions()
        assert ".pdf" in exts
        assert ".docx" in exts
        assert ".xlsx" in exts
        assert ".png" in exts

    def test_unsupported_extension_raises(self):
        parser = DocumentParser()
        with pytest.raises(ValueError, match="Unsupported file type"):
            parser.parse("test.xyz")

    def test_register_custom_parser(self):
        from app.document.parsers.base import BaseParser

        class DummyParser(BaseParser):
            def parse(self, file_path):
                return [DocumentSection(content="dummy")]

            def supported_extensions(self):
                return [".dummy"]

        parser = DocumentParser()
        parser.register(".dummy", DummyParser())
        assert ".dummy" in parser.supported_extensions()


class TestDocumentSection:
    def test_defaults(self):
        section = DocumentSection()
        assert section.title == ""
        assert section.content == ""
        assert section.section_type == "paragraph"
        assert section.page_number is None
        assert section.confidence == 1.0
        assert section.metadata == {}

    def test_with_values(self):
        section = DocumentSection(
            title="Test",
            content="Hello world",
            section_type="heading",
            page_number=1,
            confidence=0.95,
        )
        assert section.title == "Test"
        assert section.content == "Hello world"
        assert section.section_type == "heading"
        assert section.page_number == 1
        assert section.confidence == 0.95


class TestPDFParser:
    def test_fallback_when_no_pymupdf(self):
        from app.document.parsers.pdf_parser import PDFParser

        parser = PDFParser()
        assert ".pdf" in parser.supported_extensions()

    def test_parse_nonexistent_file_raises(self):
        from app.document.parsers.pdf_parser import PDFParser

        parser = PDFParser()
        # PyMuPDF raises on nonexistent files
        import pytest
        with pytest.raises(Exception):
            parser.parse("/nonexistent.pdf")


class TestWordParser:
    def test_supported_extensions(self):
        from app.document.parsers.word_parser import WordParser

        parser = WordParser()
        assert ".docx" in parser.supported_extensions()


class TestExcelParser:
    def test_supported_extensions(self):
        from app.document.parsers.excel_parser import ExcelParser

        parser = ExcelParser()
        assert ".xlsx" in parser.supported_extensions()


class TestOCRParser:
    def test_supported_extensions(self):
        from app.document.parsers.ocr_parser import OCRParser

        parser = OCRParser()
        assert ".png" in parser.supported_extensions()
        assert ".jpg" in parser.supported_extensions()
