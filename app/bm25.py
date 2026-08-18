"""BM25 稀疏检索与 RRF 融合工具。

为 RAG 提供真正的 lexical 检索能力（区别于 `lexical_overlap_score` 的 token 重叠率）：
- 中文按字符 bigram + 单字保留切分（轻量、无外部分词依赖，中文场景效果好于整词切分）
- 英文/数字按单词保留
- 与稠密向量结果做 Reciprocal Rank Fusion (RRF) 融合，构成标准 hybrid retrieval
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

try:  # rank_bm25 未安装时优雅降级
    from rank_bm25 import BM25Okapi
except Exception:  # pragma: no cover
    BM25Okapi = None  # type: ignore

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


def tokenize_for_bm25(text: str) -> list[str]:
    """把文本切成 BM25 的 token 序列。

    中文连续段按字符 bigram 切分（同时保留单字），英文/数字按单词保留。
    例：'退款时效' -> ['退款', '款时', '效', '退款', '款时'...] 的去重由 BM25Okapi 内部处理。
    实现上 bigram + 单字都会保留，覆盖 '退款' 与 '时' 的交叉匹配。
    """
    text = text.lower()
    tokens: list[str] = []
    # 中文段 -> 单字 + bigram
    for seg in _CJK_RE.findall(text):
        if len(seg) == 1:
            tokens.append(seg)
            continue
        tokens.append(seg)  # 整段（<4 字时有用）
        for i in range(len(seg)):
            tokens.append(seg[i])  # 单字
            if i + 1 < len(seg):
                tokens.append(seg[i : i + 2])  # bigram
    # 英文/数字单词
    tokens.extend(_WORD_RE.findall(text))
    return tokens


def reciprocal_rank_fusion(
    ranked_id_lists: Sequence[Sequence[str]], k: int = 60
) -> list[tuple[str, float]]:
    """RRF 融合多个排序列表。

    score(id) = sum( 1 / (k + rank(id)) )，rank 从 1 开始。
    """
    scores: dict[str, float] = {}
    for ranked in ranked_id_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


class BM25Index:
    """基于 rank_bm25.BM25Okapi 的轻量索引，带类别过滤。"""

    def __init__(self) -> None:
        self._bm25: Any | None = None
        self._ids: list[str] = []
        self._categories: list[str] = []
        self._texts: list[str] = []
        self.available = BM25Okapi is not None

    def build(
        self,
        ids: Sequence[str],
        texts: Sequence[str],
        categories: Sequence[str] | None = None,
    ) -> None:
        if not self.available:
            return
        if categories is None:
            categories = [""] * len(ids)
        self._ids = list(ids)
        self._texts = list(texts)
        self._categories = list(categories)
        tokenized = [tokenize_for_bm25(t) for t in texts]
        self._bm25 = BM25Okapi(tokenized)

    def search(
        self,
        query: str,
        category: str | None = None,
        top_k: int = 5,
    ) -> list[tuple[int, float]]:
        """返回 [(corpus_index, bm25_score)]，已按分数降序，支持类别过滤。

        注意：BM25 分数可能为负（IDF 为负，语料小时常见），负分仍代表弱相关，
        排序后保留，由上层做归一化展示。
        """
        if not self._bm25:
            return []
        query_tokens = tokenize_for_bm25(query)
        if not query_tokens:
            return []
        scores = self._bm25.get_scores(query_tokens)
        candidates: list[tuple[int, float]] = []
        for i, score in enumerate(scores):
            if category and self._categories[i] not in {category, "通用", ""}:
                continue
            if score != 0.0:
                candidates.append((i, float(score)))
        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates[:top_k]

    @property
    def size(self) -> int:
        return len(self._ids)
