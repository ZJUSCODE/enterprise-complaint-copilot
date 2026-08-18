from __future__ import annotations

from fastapi.testclient import TestClient

import main


def auth_headers(client: TestClient, role: str) -> dict[str, str]:
    password = {"viewer": "Viewer@123", "analyst": "Analyst@123"}[role]
    response = client.post("/api/auth/login", json={"username": f"{role}@example.com", "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_tool_registry_exposes_mcp_readonly_tools():
    client = TestClient(main.app)
    response = client.get("/api/tools/registry?role=viewer", headers=auth_headers(client, "analyst"))
    assert response.status_code == 200
    payload = response.json()
    names = {item["name"] for item in payload["tools"]}
    assert {"query_order_status", "query_logistics_status", "query_refund_eligibility", "query_policy_by_market"}.issubset(names)
    logistics = next(item for item in payload["tools"] if item["name"] == "query_logistics_status")
    assert logistics["allowed_for_role"] is True
    assert logistics["mcp"]["annotations"]["readOnlyHint"] is True
    assert logistics["safety"]["read_only"] is True


def test_tool_registry_enforces_role_permissions():
    client = TestClient(main.app)
    response = client.post(
        "/api/tools/invoke",
        headers=auth_headers(client, "viewer"),
        json={
            "tool_name": "query_logistics_status",
            "arguments": {"order_id": "ade386486bfc747dfd8038f3b74a3c8c"},
            "role": "viewer",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == "permission_denied"


def test_tool_registry_invokes_business_tool_for_analyst():
    client = TestClient(main.app)
    response = client.post(
        "/api/tools/invoke",
        headers=auth_headers(client, "analyst"),
        json={
            "tool_name": "query_logistics_status",
            "arguments": {"order_id": "ade386486bfc747dfd8038f3b74a3c8c"},
            "role": "analyst",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tool"] == "query_logistics_status"
    assert payload["result"]["found"] is True
    assert payload["tool_trace"][0]["tool"] == "query_logistics_status"


def test_mcp_lite_tools_list_and_call():
    client = TestClient(main.app)
    headers = auth_headers(client, "analyst")
    listed = client.post("/api/mcp", headers=headers, json={"jsonrpc": "2.0", "id": "list-1", "method": "tools/list", "params": {}})
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["jsonrpc"] == "2.0"
    assert any(item["name"] == "query_policy_by_market" for item in listed_payload["result"]["tools"])

    called = client.post(
        "/api/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": "call-1",
            "method": "tools/call",
            "params": {
                "name": "query_policy_by_market",
                "arguments": {"market": "BR", "topic": "damaged fresh food refunds"},
            },
        },
    )
    assert called.status_code == 200
    payload = called.json()
    assert payload["id"] == "call-1"
    assert payload["result"]["structuredContent"]["market"] == "BR"


def test_function_agent_reuses_order_id_for_followup_tool_selection():
    original_client = main.orchestrator.function_agent.client
    try:
        main.orchestrator.function_agent.client = None
        session_id = "test-followup-tool-registry"
        first = main.orchestrator.function_agent.respond("查询订单 ade386486bfc747dfd8038f3b74a3c8c 的物流状态", session_id=session_id)
        second = main.orchestrator.function_agent.respond("那退款资格呢？", session_id=first["session_id"])
    finally:
        main.orchestrator.function_agent.client = original_client

    assert first["tool_trace"][0]["tool"] == "query_logistics_status"
    assert second["tool_trace"][0]["tool"] == "query_refund_eligibility"
    assert second["tool_trace"][0]["arguments"]["order_id"] == "ade386486bfc747dfd8038f3b74a3c8c"
