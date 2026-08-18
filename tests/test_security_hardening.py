from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

import main
from app.config import Settings
from app import runtime as runtime_module


def login(client: TestClient, username: str, password: str) -> tuple[dict[str, str], dict]:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    payload = response.json()
    return {"Authorization": f"Bearer {payload['access_token']}"}, payload["user"]


def test_authentication_is_fail_closed_unless_demo_mode_is_explicit(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setenv("AUTH_ENFORCED", "false")
    assert Settings().auth_enforced is True

    monkeypatch.setenv("DEMO_MODE", "true")
    settings = Settings()
    assert settings.demo_mode is True
    assert settings.auth_enforced is False


def test_protected_api_rejects_missing_token():
    client = TestClient(main.app)
    response = client.post(
        "/api/tools/invoke",
        json={"tool_name": "query_policy_by_market", "arguments": {"market": "BR", "topic": "refund"}},
    )
    assert response.status_code == 401


def test_request_role_cannot_elevate_authenticated_viewer():
    client = TestClient(main.app)
    headers, _ = login(client, "viewer@example.com", "Viewer@123")
    response = client.post(
        "/api/tools/invoke",
        headers=headers,
        json={
            "tool_name": "query_refund_cases",
            "arguments": {"query": "refund cases"},
            "role": "supervisor",
        },
    )
    assert response.status_code == 200
    assert response.json()["error"]["code"] == "permission_denied"


def test_tool_and_mcp_invocations_append_actor_audit_events():
    client = TestClient(main.app)
    headers, user = login(client, "analyst@example.com", "Analyst@123")
    tool_response = client.post(
        "/api/tools/invoke",
        headers=headers,
        json={"tool_name": "query_policy_by_market", "arguments": {"market": "BR", "topic": "refund"}},
    )
    assert tool_response.status_code == 200
    mcp_response = client.post(
        "/api/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": "audit-call", "method": "tools/list", "params": {}},
    )
    assert mcp_response.status_code == 200

    events = main.audit_log.recent_actions(10)
    matching = [event for event in events if event["actor_user_id"] == user["id"]]
    assert any(event["action"] == "tool.invoke" and event["before_state"]["arguments"] for event in matching)
    assert any(event["action"] == "mcp.tools/list" and event["after_state"] for event in matching)


def test_review_update_audit_records_actor_and_before_after_state():
    client = TestClient(main.app)
    headers, user = login(client, "supervisor@example.com", "Supervisor@123")
    case_id = f"REV-{uuid.uuid4().hex[:10].upper()}"
    main.get_runtime().review_queue.enqueue({
        "case_id": case_id,
        "request_id": f"REQ-{uuid.uuid4().hex}",
        "source_mode": "guardrail",
        "reason": "security regression test",
        "user_message": "blocked write intent",
    })

    response = client.post(
        f"/api/review/queue/{case_id}/status",
        headers=headers,
        json={"status": "resolved", "reviewer_note": "verified", "role": "viewer"},
    )
    assert response.status_code == 200
    event = next(item for item in main.audit_log.recent_actions(20) if item["target_id"] == case_id)
    assert event["actor_user_id"] == user["id"]
    assert event["action"] == "review.status.update"
    assert event["before_state"]["status"] == "pending"
    assert event["after_state"]["status"] == "resolved"


def test_viewer_cannot_claim_supervisor_role_to_update_review():
    client = TestClient(main.app)
    headers, _ = login(client, "viewer@example.com", "Viewer@123")
    case_id = f"REV-{uuid.uuid4().hex[:10].upper()}"
    main.get_runtime().review_queue.enqueue({
        "case_id": case_id,
        "request_id": f"REQ-{uuid.uuid4().hex}",
        "source_mode": "guardrail",
        "reason": "authorization regression test",
        "user_message": "blocked write intent",
    })

    response = client.post(
        f"/api/review/queue/{case_id}/status",
        headers=headers,
        json={"status": "resolved", "role": "supervisor"},
    )
    assert response.status_code == 200
    assert response.json()["error"]["code"] == "permission_denied"
    assert main.get_runtime().review_queue.get(case_id)["status"] == "pending"


def test_eval_task_marks_unmeasured_metrics_not_evaluated(monkeypatch, tmp_path):
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir()
    (eval_dir / "rag_eval.json").write_text(
        '[{"question":"policy?","expected_doc_id":"POL-1"}]',
        encoding="utf-8",
    )

    updates = []
    fake_runtime = SimpleNamespace(
        task_queue=SimpleNamespace(update=lambda *args, **kwargs: updates.append((args, kwargs))),
        orchestrator=SimpleNamespace(
            langchain_rag=SimpleNamespace(query=lambda *args, **kwargs: {"sources": [{"id": "POL-1"}]})
        ),
    )
    monkeypatch.setattr(runtime_module, "BASE_DIR", tmp_path)
    monkeypatch.setattr(runtime_module, "get_runtime", lambda: fake_runtime)

    runtime_module._run_eval_task("task-security-test")

    result = updates[-1][1]["result"]
    assert result["status"] == "partially_evaluated"
    assert result["metrics"] == {"citation_hit_rate": 1.0}
    assert result["metric_status"]["route_accuracy"] == "not_evaluated"
    assert "route_accuracy" not in result["metrics"]


def test_missing_eval_report_has_explicit_not_evaluated_status(monkeypatch, tmp_path):
    client = TestClient(main.app)
    headers, _ = login(client, "analyst@example.com", "Analyst@123")
    monkeypatch.setattr(runtime_module, "BASE_DIR", tmp_path)
    response = client.get("/api/eval/report", headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "status": "not_evaluated",
        "metrics": {},
        "report_path": "eval/v2_eval_report.json",
        "message": "尚未生成真实评测报告，请先运行 python scripts\\evaluate_rag.py --force-lexical。",
    }
