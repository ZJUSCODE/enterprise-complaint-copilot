from __future__ import annotations

from fastapi.testclient import TestClient

import main


def viewer_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": "viewer@example.com", "password": "Viewer@123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_viewer_cannot_use_data_query_agent():
    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        headers=viewer_headers(client),
        json={"message": "查一下质量问题退款超过100元的明细", "mode": "function_call_agent", "role": "viewer"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "permission_denied"
    assert payload["request_id"]


def test_viewer_can_use_rag_mode():
    client = TestClient(main.app)
    response = client.post(
        "/api/chat",
        headers=viewer_headers(client),
        json={"message": "3C 数码拆封后出现质量问题，应该怎么处理", "mode": "langchain_rag", "role": "viewer"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "langchain_rag"
    assert "citations" in payload


def test_viewer_cannot_read_audit_log():
    client = TestClient(main.app)
    response = client.get("/api/audit/recent?role=supervisor", headers=viewer_headers(client))
    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["error"]["code"] == "permission_denied"
