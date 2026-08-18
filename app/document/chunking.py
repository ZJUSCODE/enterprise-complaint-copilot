from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.document.parsers.base import DocumentSection

logger = logging.getLogger(__name__)


@dataclass
class ChunkMetadata:
    """Metadata for a processed chunk."""
    chunk_id: str = ""
    source_file: str = ""
    source_type: str = ""
    page_number: int | None = None
    section_title: str = ""
    heading_hierarchy: list[str] = field(default_factory=list)
    char_count: int = 0
    token_count: int = 0
    quality_score: float = 0.0
    lineage_id: str = ""


@dataclass
class Chunk:
    """A processed text chunk ready for embedding."""
    text: str = ""
    metadata: ChunkMetadata = field(default_factory=ChunkMetadata)


class ChunkingEngine:
    """Multi-strategy chunking engine."""

    def __init__(self, strategy: str = "heading", max_chars: int = 500, overlap: int = 50):
        self.strategy = strategy
        self.max_chars = max_chars
        self.overlap = overlap

    def chunk(self, sections: list[DocumentSection], source_file: str = "", source_type: str = "") -> list[Chunk]:
        """Chunk sections using the configured strategy."""
        if self.strategy == "heading":
            return self._heading_chunk(sections, source_file, source_type)
        elif self.strategy == "recursive":
            return self._recursive_chunk(sections, source_file, source_type)
        elif self.strategy == "fixed":
            return self._fixed_chunk(sections, source_file, source_type)
        elif self.strategy == "small_to_top":
            return self._small_to_top_chunk(sections, source_file, source_type)
        else:
            return self._heading_chunk(sections, source_file, source_type)

    def _heading_chunk(self, sections: list[DocumentSection], source_file: str, source_type: str) -> list[Chunk]:
        """Split by heading boundaries, then sub-chunk large sections."""
        chunks: list[Chunk] = []
        counter = 0
        current_hierarchy: list[str] = []

        for section in sections:
            if section.section_type == "heading":
                current_hierarchy = [section.title]

            counter += 1
            chunk_id = f"{source_file}_chunk_{counter:04d}"

            if len(section.content) <= self.max_chars:
                chunks.append(Chunk(
                    text=section.content,
                    metadata=ChunkMetadata(
                        chunk_id=chunk_id,
                        source_file=source_file,
                        source_type=source_type,
                        page_number=section.page_number,
                        section_title=section.title,
                        heading_hierarchy=list(current_hierarchy),
                        char_count=len(section.content),
                        token_count=self._estimate_tokens(section.content),
                        quality_score=section.metadata.get("quality_score", 0.0),
                    ),
                ))
            else:
                # Sub-chunk by sentence boundaries
                sub_texts = self._split_by_sentences(section.content, self.max_chars)
                for idx, sub_text in enumerate(sub_texts):
                    counter += 1
                    sub_id = f"{source_file}_chunk_{counter:04d}"
                    chunks.append(Chunk(
                        text=sub_text,
                        metadata=ChunkMetadata(
                            chunk_id=sub_id,
                            source_file=source_file,
                            source_type=source_type,
                            page_number=section.page_number,
                            section_title=section.title,
                            heading_hierarchy=list(current_hierarchy),
                            char_count=len(sub_text),
                            token_count=self._estimate_tokens(sub_text),
                            quality_score=section.metadata.get("quality_score", 0.0),
                        ),
                    ))

        return chunks

    def _recursive_chunk(self, sections: list[DocumentSection], source_file: str, source_type: str) -> list[Chunk]:
        """Recursive character text splitting."""
        all_text = "\n\n".join(s.content for s in sections)
        texts = self._recursive_split(all_text, self.max_chars)
        chunks = []
        for idx, text in enumerate(texts):
            chunks.append(Chunk(
                text=text,
                metadata=ChunkMetadata(
                    chunk_id=f"{source_file}_chunk_{idx + 1:04d}",
                    source_file=source_file,
                    source_type=source_type,
                    char_count=len(text),
                    token_count=self._estimate_tokens(text),
                ),
            ))
        return chunks

    def _fixed_chunk(self, sections: list[DocumentSection], source_file: str, source_type: str) -> list[Chunk]:
        """Fixed-size character-based chunking with overlap."""
        all_text = "\n\n".join(s.content for s in sections)
        chunks = []
        counter = 0
        start = 0
        while start < len(all_text):
            end = start + self.max_chars
            text = all_text[start:end]
            counter += 1
            chunks.append(Chunk(
                text=text,
                metadata=ChunkMetadata(
                    chunk_id=f"{source_file}_chunk_{counter:04d}",
                    source_file=source_file,
                    source_type=source_type,
                    char_count=len(text),
                    token_count=self._estimate_tokens(text),
                ),
            ))
            start = end - self.overlap
        return chunks

    def _small_to_top_chunk(self, sections: list[DocumentSection], source_file: str, source_type: str) -> list[Chunk]:
        """Small chunks for matching, parent context for generation."""
        chunks: list[Chunk] = []
        counter = 0

        for section in sections:
            counter += 1
            parent_id = f"{source_file}_parent_{counter:04d}"

            # Parent chunk (full section)
            chunks.append(Chunk(
                text=section.content,
                metadata=ChunkMetadata(
                    chunk_id=parent_id,
                    source_file=source_file,
                    source_type=source_type,
                    page_number=section.page_number,
                    section_title=section.title,
                    char_count=len(section.content),
                    token_count=self._estimate_tokens(section.content),
                ),
            ))

            # Child chunks (sub-splits)
            if len(section.content) > self.max_chars:
                sub_texts = self._split_by_sentences(section.content, self.max_chars)
                for idx, sub_text in enumerate(sub_texts):
                    counter += 1
                    chunks.append(Chunk(
                        text=sub_text,
                        metadata=ChunkMetadata(
                            chunk_id=f"{source_file}_chunk_{counter:04d}",
                            source_file=source_file,
                            source_type=source_type,
                            page_number=section.page_number,
                            section_title=section.title,
                            char_count=len(sub_text),
                            token_count=self._estimate_tokens(sub_text),
                        ),
                    ))

        return chunks

    def _split_by_sentences(self, text: str, max_chars: int) -> list[str]:
        """Split text at sentence boundaries."""
        sentences = re.split(r"(?<=[。！？\n.!?])", text)
        chunks = []
        current = ""
        for sent in sentences:
            if len(current) + len(sent) > max_chars and current:
                chunks.append(current.strip())
                current = sent
            else:
                current += sent
        if current.strip():
            chunks.append(current.strip())
        return chunks or [text[:max_chars]]

    def _recursive_split(self, text: str, max_chars: int) -> list[str]:
        """Recursively split text by decreasing granularity."""
        if len(text) <= max_chars:
            return [text]

        separators = ["\n\n", "\n", "。", ".", "；", ";", " "]
        for sep in separators:
            if sep in text:
                parts = text.split(sep)
                result = []
                current = ""
                for part in parts:
                    if len(current) + len(part) + len(sep) > max_chars and current:
                        result.extend(self._recursive_split(current.strip(), max_chars))
                        current = part
                    else:
                        current = (current + sep + part) if current else part
                if current.strip():
                    result.extend(self._recursive_split(current.strip(), max_chars))
                return result

        # No separator found, hard split
        return [text[i:i + max_chars] for i in range(0, len(text), max_chars)]

    def _estimate_tokens(self, text: str) -> int:
        """Rough token count estimate."""
        chinese_chars = len(re.findall(r"[一-鿿]", text))
        other_chars = len(text) - chinese_chars
        return chinese_chars + other_chars // 4
