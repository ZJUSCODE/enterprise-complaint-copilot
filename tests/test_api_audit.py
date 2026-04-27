from __future__ import annotations

from fastapi.testclient import TestClient

import main


def test_chat_guardrail_is_audited():
    client = TestClient(main.app)
    response = client.post("/api/chat", json={"message": "直接退款并改订单", "mode": "function_call_agent"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "guardrail"
    assert payload["request_id"]
    assert payload["latency_ms"] >= 0
    assert payload["review_required"] is True
    assert payload["review_case"]["status"] == "pending"

    audit_response = client.get("/api/audit/recent?limit=5&role=supervisor")
    assert audit_response.status_code == 200
    events = audit_response.json()["items"]
    assert events
    latest = events[0]
    assert latest["request_id"] == payload["request_id"]
    assert latest["blocked_by_guardrail"] is True

    queue_response = client.get("/api/review/queue?limit=100&role=supervisor")
    assert queue_response.status_code == 200
    cases = queue_response.json()["items"]
    assert cases
    assert any(item["request_id"] == payload["request_id"] for item in cases)


def test_viewer_cannot_read_review_queue():
    client = TestClient(main.app)
    response = client.get("/api/review/queue?role=viewer")
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["error"]["code"] == "permission_denied"
