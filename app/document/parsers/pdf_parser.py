from __future__ import annotations

import logging
from pathlib import Path

from app.document.parsers.base import BaseParser, DocumentSection

logger = logging.getLogger(__name__)


class PDFParser(BaseParser):
    """Parse PDF files using PyMuPDF (fitz)."""

    def supported_extensions(self) -> list[str]:
        return [".pdf"]

    def parse(self, file_path: str) -> list[DocumentSection]:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            logger.warning("PyMuPDF not installed, falling back to basic text extraction")
            return self._fallback_parse(file_path)

        sections: list[DocumentSection] = []
        doc = fitz.open(file_path)

        for page_num in range(len(doc)):
            page = doc[page_num]

            # Extract text blocks
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
            for block in blocks:
                if block["type"] == 0:  # text block
                    lines = []
                    for line in block["lines"]:
                        span_texts = [span["text"] for span in line["spans"]]
                        lines.append("".join(span_texts))
                    text = "\n".join(lines).strip()
                    if not text:
                        continue

                    # Detect section type
                    section_type = "paragraph"
                    if any(span.get("size", 0) > 14 for line in block["lines"] for span in line["spans"]):
                        section_type = "heading"

                    sections.append(DocumentSection(
                        title=self._extract_heading(text),
                        content=text,
                        section_type=section_type,
                        page_number=page_num + 1,
                        metadata={
                            "bbox": block.get("bbox"),
                            "font_sizes": [
                                span.get("size", 0)
                                for line in block["lines"]
                                for span in line["spans"]
                            ],
                        },
                    ))

                elif block["type"] == 1:  # image block
                    try:
                        img_bytes = block.get("image")
                        sections.append(DocumentSection(
                            title=f"图片 (第{page_num + 1}页)",
                            content=f"[图片: {block.get('width', '?')}x{block.get('height', '?')}]",
                            section_type="image",
                            page_number=page_num + 1,
                            raw_bytes=img_bytes,
                            metadata={"bbox": block.get("bbox")},
                        ))
                    except Exception:
                        pass

        # Extract tables (simple heuristic: look for grid-like structures)
        for page_num in range(len(doc)):
            page = doc[page_num]
            try:
                tables = page.find_tables()
                for table_idx, table in enumerate(tables):
                    rows = []
                    for row in table.extract():
                        cells = [str(cell).strip() if cell else "" for cell in row]
                        rows.append(cells)
                    if rows:
                        content = "\n".join(" | ".join(row) for row in rows)
                        sections.append(DocumentSection(
                            title=f"表格 (第{page_num + 1}页, #{table_idx + 1})",
                            content=content,
                            section_type="table",
                            page_number=page_num + 1,
                            metadata={"rows": rows, "bbox": table.bbox},
                        ))
            except Exception:
                pass

        doc.close()
        return sections if sections else [DocumentSection(content="[空文档]")]

    def _extract_heading(self, text: str) -> str:
        """Extract first line as heading if text is multi-line."""
        first_line = text.split("\n", 1)[0].strip()
        return first_line[:100] if len(first_line) > 5 else ""

    def _fallback_parse(self, file_path: str) -> list[DocumentSection]:
        """Fallback when PyMuPDF is not available."""
        return [DocumentSection(
            title=Path(file_path).stem,
            content=f"[PDF 解析需要安装 PyMuPDF: pip install PyMuPDF]",
            section_type="paragraph",
            metadata={"file": file_path, "parser": "fallback"},
        )]
