from __future__ import annotations

import logging
from pathlib import Path

from app.document.parsers.base import BaseParser, DocumentSection

logger = logging.getLogger(__name__)


class OCRParser(BaseParser):
    """Parse images/scanned docs using PaddleOCR."""

    def supported_extensions(self) -> list[str]:
        return [".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"]

    def parse(self, file_path: str) -> list[DocumentSection]:
        try:
            from paddleocr import PaddleOCR
        except ImportError:
            logger.warning("PaddleOCR not installed")
            return [DocumentSection(
                title=Path(file_path).stem,
                content="[OCR 解析需要安装 PaddleOCR: pip install paddleocr paddlepaddle]",
                metadata={"file": file_path, "parser": "fallback"},
            )]

        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        result = ocr.ocr(file_path, cls=True)

        sections: list[DocumentSection] = []
        if not result or not result[0]:
            return [DocumentSection(
                title=Path(file_path).stem,
                content="[未识别到文字]",
                section_type="paragraph",
                confidence=0.0,
            )]

        # Group text blocks by proximity (simple vertical grouping)
        lines = []
        for line in result[0]:
            bbox = line[0]
            text = line[1][0]
            confidence = line[1][1]
            y_center = (bbox[0][1] + bbox[2][1]) / 2
            lines.append((y_center, text, confidence, bbox))

        # Sort by vertical position
        lines.sort(key=lambda x: x[0])

        # Group into paragraphs (lines within 20px of each other)
        current_group = []
        last_y = -1000
        for y, text, conf, bbox in lines:
            if y - last_y > 30 and current_group:
                # Flush group
                group_text = "\n".join(t for _, t, _, _ in current_group)
                avg_conf = sum(c for _, _, c, _ in current_group) / len(current_group)
                sections.append(DocumentSection(
                    title=Path(file_path).stem,
                    content=group_text,
                    section_type="paragraph",
                    confidence=round(avg_conf, 3),
                    metadata={"bbox": current_group[0][3], "line_count": len(current_group)},
                ))
                current_group = []
            current_group.append((y, text, conf, bbox))
            last_y = y

        # Flush last group
        if current_group:
            group_text = "\n".join(t for _, t, _, _ in current_group)
            avg_conf = sum(c for _, _, c, _ in current_group) / len(current_group)
            sections.append(DocumentSection(
                title=Path(file_path).stem,
                content=group_text,
                section_type="paragraph",
                confidence=round(avg_conf, 3),
                metadata={"bbox": current_group[0][3], "line_count": len(current_group)},
            ))

        return sections if sections else [DocumentSection(
            title=Path(file_path).stem,
            content="[未识别到文字]",
            confidence=0.0,
        )]
