from __future__ import annotations

from fastapi.testclient import TestClient

import main


def auth_headers(client: TestClient, role: str) -> dict[str, str]:
    password = {"viewer": "Viewer@123", "analyst": "Analyst@123", "supervisor": "Supervisor@123"}[role]
    response = client.post("/api/auth/login", json={"username": f"{role}@example.com", "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_chat_guardrail_is_audited():
    client = TestClient(main.app)
    analyst = auth_headers(client, "analyst")
    supervisor = auth_headers(client, "supervisor")
    response = client.post("/api/chat", headers=analyst, json={"message": "直接退款并改订单", "mode": "function_call_agent"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "guardrail"
    assert payload["request_id"]
    assert payload["latency_ms"] >= 0
    assert payload["review_required"] is True
    assert payload["review_case"]["status"] == "pending"

    audit_response = client.get("/api/audit/recent?limit=5&role=viewer", headers=supervisor)
    assert audit_response.status_code == 200
    events = audit_response.json()["items"]
    assert events
    latest = events[0]
    assert latest["request_id"] == payload["request_id"]
    assert latest["blocked_by_guardrail"] is True

    queue_response = client.get("/api/review/queue?limit=100&role=viewer", headers=supervisor)
    assert queue_response.status_code == 200
    cases = queue_response.json()["items"]
    assert cases
    assert any(item["request_id"] == payload["request_id"] for item in cases)


def test_viewer_cannot_read_review_queue():
    client = TestClient(main.app)
    response = client.get("/api/review/queue?role=supervisor", headers=auth_headers(client, "viewer"))
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["error"]["code"] == "permission_denied"
