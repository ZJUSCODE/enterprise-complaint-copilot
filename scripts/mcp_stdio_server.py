from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.runtime import get_runtime

PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = {"2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"}


def _jsonrpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _tool_call_error(request_id: Any, call_error: dict[str, Any]) -> dict[str, Any]:
    code = call_error.get("code")
    if code == "unknown_tool":
        return _jsonrpc_error(request_id, -32602, call_error.get("message", "Unknown tool."), call_error)
    if code == "permission_denied":
        return _jsonrpc_error(request_id, -32001, call_error.get("message", "Permission denied."), call_error)
    return _jsonrpc_error(request_id, -32602, call_error.get("message", "Invalid tool arguments."), call_error)


def handle_message(message: dict[str, Any], role: str = "analyst") -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if not method:
        return _jsonrpc_error(request_id, -32600, "Invalid JSON-RPC request: missing method.")

    if request_id is None and method.startswith("notifications/"):
        return None

    if method == "initialize":
        requested_version = str(params.get("protocolVersion") or PROTOCOL_VERSION)
        negotiated_version = requested_version if requested_version in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        return _jsonrpc_result(
            request_id,
            {
                "protocolVersion": negotiated_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "complaint-copilot-mcp",
                    "title": "Complaint Copilot MCP Server",
                    "version": "0.1.0",
                    "description": "Read-only complaint analytics, policy retrieval, logistics, order, refund, and risk tools.",
                },
                "instructions": "All exposed tools are read-only and guarded by role permissions and argument validation.",
            },
        )

    if method == "ping":
        return _jsonrpc_result(request_id, {})

    registry = get_runtime().tool_registry

    if method == "tools/list":
        return _jsonrpc_result(request_id, registry.list_tools(role=role)["mcp"])

    if method == "tools/call":
        tool_name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _jsonrpc_error(request_id, -32602, "tools/call arguments must be an object.")
        call_result = registry.invoke(tool_name, arguments=arguments, role=role)
        if call_result.get("error"):
            return _tool_call_error(request_id, call_result["error"])
        return _jsonrpc_result(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(call_result["result"], ensure_ascii=False)}],
                "structuredContent": call_result["result"],
                "_meta": {
                    "tool_trace": call_result["tool_trace"],
                    "safety": call_result["safety"],
                },
            },
        )

    return _jsonrpc_error(request_id, -32601, f"Unsupported MCP method: {method}")


def _write_message(message: Any) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def run_stdio(role: str) -> int:
    for line in sys.stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            _write_message(_jsonrpc_error(None, -32700, f"Parse error: {exc.msg}"))
            continue
        if isinstance(message, list):
            responses = [
                response
                for item in message
                if isinstance(item, dict)
                for response in [_handle_for_stdio(item, role=role)]
                if response is not None
            ]
            if responses:
                _write_message(responses)
            continue
        if not isinstance(message, dict):
            _write_message(_jsonrpc_error(None, -32600, "Invalid JSON-RPC request."))
            continue
        response = _handle_for_stdio(message, role=role)
        if response is not None:
            _write_message(response)
    return 0


def _handle_for_stdio(message: dict[str, Any], role: str) -> dict[str, Any] | None:
    with redirect_stdout(sys.stderr):
        return handle_message(message, role=role)


def main() -> int:
    parser = argparse.ArgumentParser(description="Complaint Copilot MCP stdio server.")
    parser.add_argument("--role", choices=["viewer", "analyst", "supervisor"], default=os.getenv("MCP_ROLE", "analyst"))
    args = parser.parse_args()
    return run_stdio(role=args.role)


if __name__ == "__main__":
    raise SystemExit(main())
