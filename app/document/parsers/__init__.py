"""Document parsers package."""

from app.document.parsers.base import BaseParser, DocumentSection
from app.document.parsers.pdf_parser import PDFParser
from app.document.parsers.word_parser import WordParser
from app.document.parsers.excel_parser import ExcelParser
from app.document.parsers.ocr_parser import OCRParser

__all__ = [
    "BaseParser",
    "DocumentSection",
    "PDFParser",
    "WordParser",
    "ExcelParser",
    "OCRParser",
]
