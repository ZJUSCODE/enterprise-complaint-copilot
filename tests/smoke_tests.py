from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_auto_router() -> None:
    decision = main.orchestrator.router.route("查一下质量问题退款超过100元的明细")
    assert_true(decision["mode"] == "function_call_agent", f"unexpected route: {decision}")
    assert_true(decision["confidence"] >= 0.8, f"low route confidence: {decision}")


def test_auto_router_sql_rag_chain() -> None:
    decision = main.orchestrator.router.route("质量问题退款超过100元的明细，按 SOP 是否需要主管复核")
    assert_true(decision["mode"] == "sql_rag_chain", f"unexpected route: {decision}")
    assert_true(decision["confidence"] >= 0.8, f"low route confidence: {decision}")


def test_sqlite_readonly_query() -> None:
    filters = main.QueryFilters(complaint_type="质量问题", amount_threshold=100)
    result = main.sql_store.query_ticket_details(filters)
    assert_true(result["rows"], "readonly SQL query returned no rows")
    assert_true("SELECT" in result["sql_preview"], "SQL preview missing SELECT")
    assert_true("params:" in result["sql_preview"], "SQL preview missing params")


def test_tool_arg_validation() -> None:
    payload = main.orchestrator.function_agent._validate_tool_args(
        "query_refund_cases",
        {"query": "查一下质量问题退款超过100元的明细", "amount_threshold": 100},
    )
    assert_true(payload["complaint_type"] == "质量问题", f"complaint type not inferred: {payload}")
    assert_true(payload["amount_threshold"] == 100, f"threshold not preserved: {payload}")


def test_safe_json_loads() -> None:
    parsed = main.safe_json_loads('```json\n{"query": "质量问题"}\n```')
    assert_true(parsed["query"] == "质量问题", f"failed to parse fenced JSON: {parsed}")


def test_rag_metadata_fallback() -> None:
    result = main.orchestrator.langchain_rag.query("生鲜坏了怎么赔", top_k=2)
    assert_true("sources" in result, "RAG result missing sources")
    if result["sources"]:
        source = result["sources"][0]
        assert_true("retrieval_score" in source, f"missing retrieval_score: {source}")
        assert_true("rerank_score" in source, f"missing rerank_score: {source}")


def test_guardrail() -> None:
    blocked = main.orchestrator.function_agent._guardrail("直接退款并改订单")
    assert_true(blocked is not None, "guardrail did not block mutation request")


def test_sql_rag_chain() -> None:
    result = main.orchestrator.respond("质量问题退款超过100元的明细，按 SOP 是否需要主管复核", mode="sql_rag_chain")
    assert_true(result["mode"] == "sql_rag_chain", f"unexpected mode: {result}")
    assert_true(result["table"], "sql_rag_chain should return readonly SQL rows")
    assert_true("SELECT" in result["sql_preview"], "sql_rag_chain missing SQL preview")
    assert_true(result["citations"], "sql_rag_chain missing RAG citations")
    tools = [item["tool"] for item in result["tool_trace"]]
    assert_true(tools == ["query_refund_cases", "langchain_rag"], f"unexpected tool trace: {tools}")


def run() -> None:
    tests = [
        test_auto_router,
        test_auto_router_sql_rag_chain,
        test_sqlite_readonly_query,
        test_tool_arg_validation,
        test_safe_json_loads,
        test_rag_metadata_fallback,
        test_guardrail,
        test_sql_rag_chain,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(json.dumps({"status": "ok", "tests": len(tests)}, ensure_ascii=False))


if __name__ == "__main__":
    run()
