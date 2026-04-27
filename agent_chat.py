from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


API_URL = os.getenv("COPILOT_API_URL", "http://127.0.0.1:8000/api/chat")


def ask_copilot(message: str, mode: str = "auto", session_id: str | None = None) -> dict:
    payload = json.dumps(
        {"message": message, "mode": mode, "session_id": session_id},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def print_response(payload: dict) -> None:
    print(f"\n[{payload.get('title', 'Copilot')}]")
    print(payload.get("summary", ""))
    if payload.get("highlights"):
        print("\n要点：")
        for item in payload["highlights"][:6]:
            print(f"- {item}")
    if payload.get("tool_trace"):
        print("\nTool Trace：")
        for item in payload["tool_trace"]:
            print(f"- {item.get('tool')}: {item.get('arguments')}")


if __name__ == "__main__":
    print(f"Copilot CLI ready. Endpoint: {API_URL}")
    current_session_id = None
    while True:
        user_query = input("\n业务问题 >> ").strip()
        if user_query.lower() in {"quit", "exit", "退出"}:
            break
        if not user_query:
            continue
        try:
            result = ask_copilot(user_query, session_id=current_session_id)
            current_session_id = result.get("session_id") or current_session_id
            print_response(result)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"\n请求失败：{exc}")
