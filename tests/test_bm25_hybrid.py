"""BM25 稀疏检索 + RRF 融合的单元测试。"""
from __future__ import annotations

import json

import pytest

from app.bm25 import BM25Index, reciprocal_rank_fusion, tokenize_for_bm25
from app.config import Settings
from app.rag import LangChainRAGService, PolicyKnowledgeBase


class TestTokenizer:
    def test_chinese_bigram_and_single_chars(self):
        tokens = tokenize_for_bm25("退款时效")
        assert "退款" in tokens
        assert "款时" in tokens  # bigram 交叉
        assert "时" in tokens    # 单字保留
        assert "效" in tokens

    def test_english_words_preserved(self):
        tokens = tokenize_for_bm25("Apple iPhone 15 退款")
        assert "apple" in tokens
        assert "iphone" in tokens
        assert "15" in tokens

    def test_lowercase(self):
        tokens = tokenize_for_bm25("SN 码")
        assert "sn" in tokens


class TestRRF:
    def test_fusion_orders_by_reciprocal_rank(self):
        a = ["d1", "d2", "d3"]
        b = ["d2", "d4", "d1"]
        fused = reciprocal_rank_fusion([a, b], k=60)
        ids = [doc_id for doc_id, _ in fused]
        # d2 在两个列表都排第 1，应排第一；d1 在两列表出现，d4 只在 b 出现
        assert ids[0] == "d2"
        assert set(ids[:2]) == {"d2", "d1"}

    def test_empty_input(self):
        assert reciprocal_rank_fusion([[], []]) == []


class TestBM25Index:
    def _build(self) -> BM25Index:
        idx = BM25Index()
        idx.build(
            ids=["p1", "p2", "p3"],
            texts=[
                "生鲜水果签收后坏损可以按比例申请退款，生鲜赔付分级按坏损率计算",
                "3C 数码商品拆封后影响二次销售，不支持无理由退货",
                "物流延误超过七天可以申请丢件理赔并获取优惠券补偿",
            ],
            categories=["生鲜", "3C数码", "物流"],
        )
        return idx

    def test_relevance_ranking(self):
        idx = self._build()
        hits = idx.search("生鲜坏损怎么退款", top_k=3)
        assert hits, "应检索到结果"
        assert hits[0][0] == 0  # 生鲜文档排第一
        assert hits[0][1] > hits[-1][1]

    def test_category_filter(self):
        idx = self._build()
        hits = idx.search("物流延误理赔", category="物流", top_k=5)
        # 物流类只允许命中物流文档（或通用）
        idx_hit = {i for i, _ in hits}
        assert all(i != 0 for i in idx_hit)  # 生鲜文档被过滤
        assert 2 in idx_hit                  # 物流文档命中

    def test_skip_when_no_corpus(self):
        idx = BM25Index()
        assert idx.search("anything") == []
        assert idx.size == 0


class TestFallbackBM25:
    def test_fallback_uses_bm25_when_vector_unavailable(self, tmp_path, monkeypatch):
        """无 embedding key 时（向量不可用），query 应走 bm25_fallback 而非纯 lexical。"""
        from app import rag as rag_module

        # 构造临时知识库目录（一个 policy + 一个小 md）
        kb_dir = tmp_path / "kb"
        (kb_dir / "sop").mkdir(parents=True)
        (kb_dir / "policies.json").write_text(
            json.dumps([
                {
                    "id": "T-001",
                    "title": "测试政策",
                    "category": "生鲜",
                    "keywords": ["生鲜", "坏损", "退款"],
                    "excerpt": "生鲜坏损按比例退款。",
                    "guidance": ["先取证据", "再核算比例"],
                    "citation": "《测试SOP》1.1",
                }
            ]),
            encoding="utf-8",
        )
        (kb_dir / "sop" / "sop_fresh_test.md").write_text(
            "# 生鲜测试 SOP\n\n## 坏损赔付\n\n生鲜水果坏损按坏损率分级赔付，超过百分之六十全额退款。",
            encoding="utf-8",
        )
        monkeypatch.setattr(rag_module, "KB_DIR", kb_dir)

        settings = Settings(use_langchain_rag=True, embedding_api_key="", llm_api_key="")
        kb = PolicyKnowledgeBase(kb_dir / "policies.json")
        service = LangChainRAGService(settings, kb)

        assert service.available is False
        assert service.bm25_index.size > 0, "BM25 索引应构建成功（不依赖 embedding）"

        result = service.query("生鲜水果坏损怎么赔付", top_k=3)
        assert result["retrieval_mode"] == "bm25_fallback"
        assert result["sources"], "应检索到来源"
        assert any(s["source"] == "bm25" for s in result["sources"])

    def test_tokenize_regression(self):
        # 中文整段 + bigram 覆盖 '生鲜' 与 '赔付' 的组合匹配
        tokens = tokenize_for_bm25("生鲜赔付")
        assert "生鲜" in tokens
        assert "鲜赔" in tokens
