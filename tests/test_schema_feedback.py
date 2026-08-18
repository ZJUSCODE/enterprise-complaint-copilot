from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

import main


def auth_headers(client: TestClient, role: str = "analyst") -> dict[str, str]:
    password = "Analyst@123" if role == "analyst" else "Viewer@123"
    response = client.post("/api/auth/login", json={"username": f"{role}@example.com", "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_schema_endpoint_describes_tickets_table():
    client = TestClient(main.app)
    response = client.get("/api/schema", headers=auth_headers(client, "viewer"))
    assert response.status_code == 200
    payload = response.json()
    table = payload["tables"][0]
    fields = {column["name"] for column in table["columns"]}
    assert table["name"] == "tickets"
    assert {"order_id", "user_id", "category", "complaint_type", "compensation_amount"}.issubset(fields)
    assert "category" in payload["filterable_dimensions"]
    assert payload["safety"]["validator"] == "validate_readonly_sql"


def test_feedback_endpoint_records_rating_event():
    client = TestClient(main.app)
    request_id = f"test-{uuid.uuid4().hex}"
    response = client.post(
        "/api/feedback",
        headers=auth_headers(client),
        json={
            "request_id": request_id,
            "session_id": "session-test",
            "rating": "down",
            "comment": "字段解释还可以更清楚",
            "role": "analyst",
        },
    )
    assert response.status_code == 200
    item = response.json()["item"]
    assert item["request_id"] == request_id
    assert item["rating"] == "down"
    assert item["comment"] == "字段解释还可以更清楚"

    recent = main.feedback_events.recent(20)
    assert any(event["request_id"] == request_id and event["rating"] == "down" for event in recent)
