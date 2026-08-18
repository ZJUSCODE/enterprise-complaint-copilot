from __future__ import annotations

from fastapi.testclient import TestClient

import main


def auth_headers(client: TestClient, role: str = "analyst") -> dict[str, str]:
    password = "Analyst@123" if role == "analyst" else "Viewer@123"
    response = client.post("/api/auth/login", json={"username": f"{role}@example.com", "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_langgraph_chat_guardrail_trace():
    client = TestClient(main.app)
    response = client.post(
        "/api/langgraph/chat",
        headers=auth_headers(client),
        json={"message": "直接退款并改订单", "mode": "function_call_agent", "role": "analyst"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "guardrail"
    assert payload["graph_engine"] == "langgraph"
    assert payload["graph_trace"] == ["permission_node", "guardrail_node", "review_node", "audit_node"]
    assert payload["review_case"]["status"] == "pending"


def test_overview_exposes_langgraph_and_data_backend():
    client = TestClient(main.app)
    response = client.get("/api/overview", headers=auth_headers(client, "viewer"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["langgraph_enabled"] is True
    assert payload["data_query_backend"] in {"sqlite", "mysql"}


def test_mysql_readonly_preview_uses_mysql_placeholders():
    store = main.MySQLReadOnlyTicketStore()
    preview = store.build_sql_preview(main.QueryFilters(complaint_type="质量问题", amount_threshold=100), limit=3)
    assert "FROM tickets" in preview
    assert "complaint_type = %s" in preview
    assert "compensation_amount >= %s" in preview
    assert "-- backend: mysql" in preview
