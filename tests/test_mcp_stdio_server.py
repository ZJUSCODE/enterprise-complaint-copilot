from __future__ import annotations

from scripts import mcp_stdio_server


def test_mcp_stdio_initialize_and_tools_list():
    initialized = mcp_stdio_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": "init-1",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1.0.0"},
            },
        }
    )
    assert initialized is not None
    assert initialized["result"]["protocolVersion"] == "2025-11-25"
    assert "tools" in initialized["result"]["capabilities"]
    assert initialized["result"]["serverInfo"]["name"] == "complaint-copilot-mcp"

    listed = mcp_stdio_server.handle_message({"jsonrpc": "2.0", "id": "tools-1", "method": "tools/list"}, role="analyst")
    assert listed is not None
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert {"query_logistics_status", "query_policy_by_market"}.issubset(names)


def test_mcp_stdio_tools_call_uses_readonly_registry():
    called = mcp_stdio_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": "call-1",
            "method": "tools/call",
            "params": {
                "name": "query_policy_by_market",
                "arguments": {"market": "BR", "topic": "damaged fresh food refunds"},
            },
        },
        role="analyst",
    )
    assert called is not None
    assert called["result"]["structuredContent"]["market"] == "BR"
    assert called["result"]["_meta"]["safety"]["read_only"] is True


def test_mcp_stdio_notification_returns_no_response():
    response = mcp_stdio_server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert response is None
