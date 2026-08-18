from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DocumentSection:
    """A structured section extracted from a document."""
    title: str = ""
    content: str = ""
    section_type: str = "paragraph"  # heading / paragraph / table / image / code
    page_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_bytes: bytes | None = None
    confidence: float = 1.0


class BaseParser(ABC):
    """Abstract base for all document parsers."""

    @abstractmethod
    def parse(self, file_path: str) -> list[DocumentSection]:
        """Parse file into structured sections."""
        ...

    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """Return list of supported file extensions (e.g. ['.pdf'])."""
        ...
