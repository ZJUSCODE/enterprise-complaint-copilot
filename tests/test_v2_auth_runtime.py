from __future__ import annotations

from fastapi.testclient import TestClient

import main


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": "analyst@example.com", "password": "Analyst@123"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_login_returns_jwt_and_me_reads_user():
    client = TestClient(main.app)
    response = client.post("/api/auth/login", json={"username": "analyst@example.com", "password": "Analyst@123"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert payload["user"]["role"] == "analyst"

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {payload['access_token']}"})
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "analyst@example.com"


def test_chat_response_contains_trace_cost_retry_fields():
    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={"message": "查询质量问题退款超过100元的明细", "mode": "function_call_agent", "response_language": "zh"},
        headers=auth_headers(client),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"]
    assert payload["trace_id"]
    assert "token_usage" in payload
    assert "estimated_cost_usd" in payload
    assert "retry_count" in payload
    assert payload["trace"]["tool_call_count"] >= 1


def test_langchain_rag_response_exposes_detailed_usage():
    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={"message": "3C 数码拆封后出现质量问题，应该怎么处理", "mode": "langchain_rag"},
        headers=auth_headers(client),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "langchain_rag"
    assert payload["token_usage"]["total_tokens"] >= payload["token_usage"]["completion_tokens"]
    assert "embedding_tokens" in payload["token_usage"]
    assert set(payload["cost_breakdown"]) >= {"embedding_cost_usd", "prompt_cost_usd", "completion_cost_usd", "total_cost_usd"}
    assert payload["tool_trace"][0]["token_usage"]["total_tokens"] == payload["token_usage"]["total_tokens"]


def test_sql_rag_chain_carries_rag_token_usage_to_audit_shape():
    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        json={"message": "质量问题退款超过100元的明细，按 SOP 是否需要主管复核", "mode": "sql_rag_chain"},
        headers=auth_headers(client),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "sql_rag_chain"
    assert payload["token_usage"]["total_tokens"] > 0
    assert payload["cost_breakdown"]["total_cost_usd"] == payload["estimated_cost_usd"]
    assert payload["summary"]
    assert payload["tool_trace"][0]["tool"] == "query_refund_cases"
    assert "随后已用 SQL 摘要检索" not in payload["summary"]
    rag_step = next(item for item in payload["tool_trace"] if item["tool"] == "langchain_rag")
    assert payload["token_usage"]["total_tokens"] >= rag_step["token_usage"]["total_tokens"]


def test_new_business_tool_fallback_selects_logistics():
    result = main.orchestrator.function_agent.respond("订单 ade386486bfc747dfd8038f3b74a3c8c 的物流状态是什么？")
    assert result["tool_trace"][0]["tool"] == "query_logistics_status"
    assert "duration_ms" in result["tool_trace"][0]
