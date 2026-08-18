from __future__ import annotations

import hashlib
from datetime import date

from app.function_agent import FunctionCallingAgent
from app.rag import PolicyKnowledgeBase
from scripts.reset_demo_data import build_databases, generate_data, validate_staged_reset


def _tree_hash(path) -> str:
    digest = hashlib.sha256()
    for item in sorted(path.glob("*.csv")):
        digest.update(item.name.encode())
        digest.update(item.read_bytes())
    return digest.hexdigest()


def test_demo_data_generation_is_deterministic_and_valid(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_summary = generate_data(first, end_date=date(2026, 7, 28), days=30, seed=20260729)
    second_summary = generate_data(second, end_date=date(2026, 7, 28), days=30, seed=20260729)
    sqlite_path = tmp_path / "tickets.sqlite3"
    build_databases(first, sqlite_path)
    validate_staged_reset(first, sqlite_path, first_summary)
    assert first_summary == second_summary
    assert _tree_hash(first) == _tree_hash(second)


def test_grouped_text_to_sql_query_is_not_silently_downgraded():
    reason = FunctionCallingAgent._unsupported_query_reason("退货最多的类目是什么")
    assert reason is not None
    assert "不支持" in reason
    assert FunctionCallingAgent._unsupported_query_reason("质量问题赔付超过100元的明细") is None


def test_lexical_rag_excludes_unrelated_categories(tmp_path):
    policy_path = tmp_path / "policies.json"
    policy_path.write_text(
        """[
          {"id":"fresh","title":"生鲜规则","category":"生鲜","excerpt":"坏果处理","guidance":[],"citation":"fresh","keywords":["坏果"]},
          {"id":"digital","title":"数码规则","category":"3C数码","excerpt":"拆封处理","guidance":[],"citation":"digital","keywords":["拆封"]},
          {"id":"general","title":"通用规则","category":"通用","excerpt":"人工复核","guidance":[],"citation":"general","keywords":["复核"]}
        ]""",
        encoding="utf-8",
    )
    knowledge_base = PolicyKnowledgeBase(policy_path)
    results = knowledge_base.lexical_search("拆封坏果复核", category="生鲜", top_k=5)
    assert {item["id"] for item in results} == {"fresh", "general"}
