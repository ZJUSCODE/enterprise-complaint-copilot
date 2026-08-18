"""WeKnora 外部检索后端（可切换检索层）的单元测试。"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.retrieval_backend import WeKnoraBackend


class FakeResponse:
    def __init__(self, body: dict, status: int = 200):
        self._body = body
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
        return None

    def json(self) -> dict:
        return self._body


class TestWeKnoraBackend:
    def test_available_requires_config(self):
        assert not WeKnoraBackend("", "", "").available
        assert WeKnoraBackend("http://localhost:8080", "sk-x", "kb-1").available

    @patch("app.retrieval_backend.httpx.post")
    def test_search_builds_request_and_maps_response(self, mock_post):
        backend = WeKnoraBackend("http://localhost:8080", "sk-x", "kb-1")
        mock_post.return_value = FakeResponse({
            "success": True,
            "data": [
                {
                    "id": "chunk-1",
                    "content": "生鲜坏损按坏损率分级赔付，超过百分之六十全额退款。",
                    "knowledge_id": "knowledge-1",
                    "knowledge_title": "生鲜赔付标准",
                    "knowledge_filename": "sop_fresh.md",
                    "chunk_index": 2,
                    "score": 0.93,
                }
            ],
        })
        sources = backend.search("生鲜坏损怎么赔", top_k=3)
        # 请求构造校验
        args, kwargs = mock_post.call_args
        assert args[0] == "http://localhost:8080/api/v1/knowledge-search"
        assert kwargs["headers"]["X-API-Key"] == "sk-x"
        assert kwargs["json"] == {"query": "生鲜坏损怎么赔", "knowledge_base_id": "kb-1"}
        # 响应映射校验
        assert len(sources) == 1
        assert sources[0]["source"] == "weknora"
        assert sources[0]["id"] == "chunk-1"
        assert sources[0]["title"] == "生鲜赔付标准"
        assert sources[0]["citation"] == "sop_fresh.md"
        assert "生鲜坏损" in sources[0]["excerpt"]
        assert sources[0]["retrieval_score"] == 0.93
        assert sources[0]["chunk_index"] == 2

    @patch("app.retrieval_backend.httpx.post")
    def test_search_returns_empty_on_error(self, mock_post):
        backend = WeKnoraBackend("http://localhost:8080", "sk-x", "kb-1")
        mock_post.side_effect = RuntimeError("connection refused")
        assert backend.search("anything") == []
        assert backend.error is not None

    @patch("app.retrieval_backend.httpx.post")
    def test_search_empty_when_not_available(self, mock_post):
        backend = WeKnoraBackend("", "", "")
        assert backend.search("anything") == []
        mock_post.assert_not_called()


class TestSettingsAndWiring:
    def test_settings_parse_weknora_env(self, monkeypatch):
        from app.config import Settings

        monkeypatch.setenv("RETRIEVAL_BACKEND", "weknora")
        monkeypatch.setenv("WEKNORA_BASE_URL", "http://localhost:8080/")
        monkeypatch.setenv("WEKNORA_API_KEY", "sk-test")
        monkeypatch.setenv("WEKNORA_KB_ID", "kb-999")
        s = Settings()
        assert s.retrieval_backend == "weknora"
        assert s.weknora_base_url == "http://localhost:8080"  # 去尾部斜杠
        assert s.weknora_api_key == "sk-test"
        assert s.weknora_kb_id == "kb-999"

    def test_service_uses_weknora_when_configured(self, monkeypatch, tmp_path):
        """配置 weknora 后端后，query 应走 weknora 检索分支。"""
        import app.rag as rag_module
        from app.config import Settings
        from app.rag import LangChainRAGService, PolicyKnowledgeBase

        for k, v in {
            "LLM_API_KEY": "sk-fake",
            "RETRIEVAL_BACKEND": "weknora",
            "WEKNORA_BASE_URL": "http://localhost:8080",
            "WEKNORA_API_KEY": "sk-x",
            "WEKNORA_KB_ID": "kb-1",
        }.items():
            monkeypatch.setenv(k, v)

        kb_dir = tmp_path / "kb"
        (kb_dir / "sop").mkdir(parents=True)
        (kb_dir / "policies.json").write_text(json.dumps([{
            "id": "T-001", "title": "测试政策", "category": "通用",
            "keywords": [], "excerpt": "占位。", "guidance": [], "citation": "《占位》1.1",
        }]), encoding="utf-8")
        (kb_dir / "sop" / "sop_placeholder.md").write_text("# 占位\n\n占位内容。", encoding="utf-8")
        monkeypatch.setattr(rag_module, "KB_DIR", kb_dir)

        settings = Settings()
        kb = PolicyKnowledgeBase(kb_dir / "policies.json")
        service = LangChainRAGService(settings, kb)
        assert service.weknora_backend is not None

        # mock 掉 weknora 检索与生成，验证走 weknora 分支
        service.weknora_backend.search = MagicMock(return_value=[{
            "id": "c1", "title": "生鲜赔付", "category": "生鲜",
            "citation": "sop_fresh.md", "excerpt": "生鲜坏损按坏损率分级赔付。",
            "retrieval_score": 0.9, "rerank_score": 0.0, "source": "weknora",
        }])
        service.generation_client = MagicMock()
        service.generation_client.chat.completions.create.return_value.choices[0].message.content = "按坏损率分级赔付。"
        service.settings.llm_model = "mock-model"

        result = service.query("生鲜坏损怎么赔", top_k=3)
        assert result["retrieval_mode"] == "weknora"
        assert result["sources"][0]["source"] == "weknora"
        assert "按坏损率" in result["answer"]

    def test_service_falls_back_when_weknora_empty(self, monkeypatch, tmp_path):
        """WeKnora 检索无结果时回退本地 BM25/词法。"""
        import app.rag as rag_module
        from app.config import Settings
        from app.rag import LangChainRAGService, PolicyKnowledgeBase

        for k, v in {
            "LLM_API_KEY": "sk-fake",
            "RETRIEVAL_BACKEND": "weknora",
            "WEKNORA_BASE_URL": "http://localhost:8080",
            "WEKNORA_API_KEY": "sk-x",
            "WEKNORA_KB_ID": "kb-1",
        }.items():
            monkeypatch.setenv(k, v)

        kb_dir = tmp_path / "kb"
        (kb_dir / "sop").mkdir(parents=True)
        (kb_dir / "policies.json").write_text(json.dumps([{
            "id": "T-001", "title": "生鲜政策", "category": "生鲜",
            "keywords": ["生鲜", "退款"],
            "excerpt": "生鲜坏损按比例退款。",
            "guidance": ["先取证"], "citation": "《测试》1.1",
        }]), encoding="utf-8")
        (kb_dir / "sop" / "sop_fresh_test.md").write_text("# 生鲜 SOP\n\n生鲜坏损可退款。", encoding="utf-8")
        monkeypatch.setattr(rag_module, "KB_DIR", kb_dir)

        settings = Settings()
        kb = PolicyKnowledgeBase(kb_dir / "policies.json")
        service = LangChainRAGService(settings, kb)
        service.weknora_backend.search = MagicMock(return_value=[])
        service.generation_client = MagicMock()
        service.generation_client.chat.completions.create.return_value.choices[0].message.content = "本地兜底回答。"

        result = service.query("生鲜坏损怎么赔", top_k=3)
        # 回退到本地 BM25（weknora 无结果）
        assert result["retrieval_mode"] in ("bm25_fallback", "lexical")
