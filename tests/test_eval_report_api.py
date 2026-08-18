from __future__ import annotations

from fastapi.testclient import TestClient

import main


def auth_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_eval_report_visible_to_analyst():
    client = TestClient(main.app)
    response = client.get(
        "/api/eval/report",
        headers=auth_headers(client, "analyst@example.com", "Analyst@123"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "evaluated"
    assert payload["total"] == {
        "all_cases": 57,
        "rag_cases": 18,
        "route_cases": 15,
        "tool_cases": 10,
        "guardrail_cases": 12,
        "memory_cases": 2,
    }
    assert payload["total"]["all_cases"] == sum(
        count for name, count in payload["total"].items() if name != "all_cases"
    )
    assert "route_accuracy" in payload["metrics"]
    assert payload["report_path"] == "eval/v2_eval_report.json"


def test_viewer_cannot_read_eval_report():
    client = TestClient(main.app)
    response = client.get(
        "/api/eval/report",
        headers=auth_headers(client, "viewer@example.com", "Viewer@123"),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == "permission_denied"
