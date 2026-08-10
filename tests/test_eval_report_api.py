from __future__ import annotations

from fastapi.testclient import TestClient

import main


def test_eval_report_visible_to_analyst():
    client = TestClient(main.app)
    response = client.get("/api/eval/report?role=analyst")
    assert response.status_code == 200
    payload = response.json()
    category_total = sum(
        value
        for key, value in payload["total"].items()
        if key.endswith("_cases") and key != "all_cases"
    )
    assert payload["total"]["all_cases"] == category_total
    assert payload["total"]["all_cases"] >= 1
    assert "route_accuracy" in payload["metrics"]
    assert payload["report_path"] == "eval/v2_eval_report.json"


def test_viewer_cannot_read_eval_report():
    client = TestClient(main.app)
    response = client.get("/api/eval/report?role=viewer")
    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == "permission_denied"
