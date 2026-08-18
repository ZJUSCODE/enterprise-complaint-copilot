from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class OnlineRAGMetrics:
    retrieval_diversity: float
    retrieval_confidence: float
    coverage_score: float
    has_citations: bool
    query_rewrite_applied: bool


def _tokenize_cjk(text: str) -> set[str]:
    """Extract meaningful tokens: individual CJK characters + ASCII word bigrams."""
    cjk_chars = set(re.findall(r"[一-鿿]", text.lower()))
    ascii_words = set(re.findall(r"[a-z0-9]{2,}", text.lower()))
    return cjk_chars | ascii_words


def compute_online_metrics(
    query: str,
    sources: list[dict[str, Any]],
    answer: str,
    rewrite_applied: bool = False,
) -> OnlineRAGMetrics:
    if not sources:
        return OnlineRAGMetrics(
            retrieval_diversity=0.0,
            retrieval_confidence=0.0,
            coverage_score=0.0,
            has_citations=False,
            query_rewrite_applied=rewrite_applied,
        )

    source_files = set()
    for s in sources:
        sf = s.get("source_file") or s.get("source") or s.get("id", "")
        source_files.add(sf)
    retrieval_diversity = round(len(source_files) / max(len(sources), 1), 4)

    scores = [s.get("retrieval_score", 0) or 0 for s in sources]
    retrieval_confidence = round(sum(scores) / max(len(scores), 1), 4)

    query_tokens = set(_tokenize_cjk(query))
    if not query_tokens:
        coverage_score = 1.0
    else:
        all_excerpt_text = " ".join(s.get("excerpt", "") or "" for s in sources)
        excerpt_tokens = set(_tokenize_cjk(all_excerpt_text))
        covered = query_tokens & excerpt_tokens
        coverage_score = round(len(covered) / len(query_tokens), 4)

    has_citations = any(s.get("retrieval_score") is not None for s in sources)

    return OnlineRAGMetrics(
        retrieval_diversity=retrieval_diversity,
        retrieval_confidence=retrieval_confidence,
        coverage_score=coverage_score,
        has_citations=has_citations,
        query_rewrite_applied=rewrite_applied,
    )
