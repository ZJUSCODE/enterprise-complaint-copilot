from __future__ import annotations

import logging
from pathlib import Path

from app.document.parsers.base import BaseParser, DocumentSection
from app.document.parsers.pdf_parser import PDFParser
from app.document.parsers.word_parser import WordParser
from app.document.parsers.excel_parser import ExcelParser
from app.document.parsers.ocr_parser import OCRParser

logger = logging.getLogger(__name__)


class DocumentParser:
    """Facade that routes files to the appropriate parser by extension."""

    def __init__(self):
        self._parsers: dict[str, BaseParser] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        for parser_cls in [PDFParser, WordParser, ExcelParser, OCRParser]:
            parser = parser_cls()
            for ext in parser.supported_extensions():
                self._parsers[ext] = parser

    def register(self, ext: str, parser: BaseParser) -> None:
        self._parsers[ext] = parser

    def supported_extensions(self) -> list[str]:
        return sorted(self._parsers.keys())

    def parse(self, file_path: str) -> list[DocumentSection]:
        ext = Path(file_path).suffix.lower()
        parser = self._parsers.get(ext)
        if not parser:
            raise ValueError(f"Unsupported file type: {ext}. Supported: {self.supported_extensions()}")
        logger.info("Parsing %s with %s", file_path, parser.__class__.__name__)
        return parser.parse(file_path)
