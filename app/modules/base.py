from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Citation:
    """A single retrieval citation."""
    id: str = ""
    title: str = ""
    category: str = ""
    citation: str = ""
    excerpt: str = ""
    retrieval_score: float = 0.0
    rerank_score: float = 0.0
    source: str = ""


@dataclass
class RAGContext:
    """Shared context flowing through the Modular RAG pipeline."""
    query: str = ""
    rewritten_query: str = ""
    sub_queries: list[str] = field(default_factory=list)
    retrieval_strategy: str = "hybrid"
    vector_results: list[Citation] = field(default_factory=list)
    kg_results: list[Citation] = field(default_factory=list)
    fused_results: list[Citation] = field(default_factory=list)
    reranked_results: list[Citation] = field(default_factory=list)
    corrected_results: list[Citation] = field(default_factory=list)
    answer: str = ""
    reflection: Any = None  # ReflectionResult
    metadata: dict[str, Any] = field(default_factory=dict)


class RAGModule(ABC):
    """Base class for all pluggable RAG modules."""
    name: str = "base_module"
    enabled: bool = True

    @abstractmethod
    async def execute(self, context: RAGContext) -> RAGContext:
        """Execute module logic and return updated context."""
        pass

    @abstractmethod
    def should_activate(self, context: RAGContext) -> bool:
        """Determine whether this module should run."""
        pass
