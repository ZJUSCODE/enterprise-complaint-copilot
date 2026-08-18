"""可切换的外部检索后端。

当前支持 WeKnora（腾讯开源知识框架，github.com/Tencent/WeKnora）：
通过环境变量 `RETRIEVAL_BACKEND=weknora` 启用后，RAG 的检索层走 WeKnora 的
`POST /api/v1/knowledge-search`（纯检索、不总结），回答生成仍由本地 LLM 管线
完成——保留项目原有的 Guardrail / 评测 / 只读 SQL 能力，仅替换检索底座。

不配置时默认走本地自研检索（Chroma 向量 + BM25 + RRF 融合），零依赖侵入。
"""
from __future__ import annotations

from typing import Any

import httpx

from app.utils import summarize_text


class WeKnoraBackend:
    """WeKnora 检索客户端（HTTP API）。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        kb_id: str,
        timeout: float = 15.0,
        search_path: str = "/api/v1/knowledge-search",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.kb_id = kb_id
        self.timeout = timeout
        self.search_path = search_path
        self.available = bool(base_url and api_key and kb_id)
        self.error: str | None = None

    def search(self, query: str, top_k: int = 5, category: str | None = None) -> list[dict[str, Any]]:
        """调用 WeKnora 纯检索接口，返回统一结构的 sources 列表。

        WeKnora 响应：{"success": true, "data": [{id, content, knowledge_title,
        knowledge_filename, score, chunk_index, ...}]}
        """
        if not self.available:
            return []
        payload: dict[str, Any] = {"query": query, "knowledge_base_id": self.kb_id}
        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        }
        try:
            resp = httpx.post(
                f"{self.base_url}{self.search_path}",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            self.error = f"WeKnora 检索失败：{exc}"
            return []
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            self.error = f"WeKnora 返回结构异常：{str(body)[:200]}"
            return []

        sources: list[dict[str, Any]] = []
        for item in data[:top_k]:
            content = item.get("content", "")
            sources.append({
                "id": item.get("id", ""),
                "title": item.get("knowledge_title", ""),
                "category": category or "",
                "citation": item.get("knowledge_filename") or item.get("knowledge_title", ""),
                "excerpt": summarize_text(content, limit=220) if len(content) > 220 else content,
                "retrieval_score": round(float(item.get("score", 0.0) or 0.0), 4),
                "rerank_score": 0.0,
                "source": "weknora",
                "chunk_index": item.get("chunk_index"),
                "knowledge_id": item.get("knowledge_id"),
            })
        return sources
