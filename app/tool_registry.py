from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from app.permissions import PermissionPolicy
from app.utils import summarize_text, timed_call


class ToolRegistry:
    TOOL_PERMISSIONS = {
        "get_user_risk": "risk:read",
        "query_refund_cases": "data:query",
        "search_policy_docs": "rag:read",
        "query_order_status": "data:query",
        "query_logistics_status": "data:query",
        "query_refund_eligibility": "data:query",
        "query_policy_by_market": "rag:read",
    }
    TOOL_KINDS = {
        "get_user_risk": "risk_profile",
        "query_refund_cases": "readonly_sql",
        "search_policy_docs": "rag_retrieval",
        "query_order_status": "order_lookup",
        "query_logistics_status": "logistics_lookup",
        "query_refund_eligibility": "refund_decision_support",
        "query_policy_by_market": "market_policy",
    }

    def __init__(self, function_agent: Any):
        self.function_agent = function_agent

    def _tool_specs(self) -> dict[str, dict[str, Any]]:
        specs: dict[str, dict[str, Any]] = {}
        for item in self.function_agent._build_tools():
            fn = item.get("function", {})
            name = fn.get("name")
            if name:
                specs[name] = fn
        return specs

    def list_tools(self, role: str = "viewer") -> dict[str, Any]:
        permissions = PermissionPolicy.permissions_for(role)
        tools = []
        mcp_tools = []
        for name, spec in self._tool_specs().items():
            required_permission = self.TOOL_PERMISSIONS.get(name, "data:query")
            allowed = required_permission in permissions
            input_schema = spec.get("parameters", {"type": "object", "properties": {}})
            item = {
                "name": name,
                "description": spec.get("description", ""),
                "kind": self.TOOL_KINDS.get(name, "business_tool"),
                "input_schema": input_schema,
                "required_permission": required_permission,
                "allowed_for_role": allowed,
                "safety": {
                    "read_only": True,
                    "side_effect_free": True,
                    "guarded_by": ["RBAC", "Pydantic argument validation", "readonly SQL validator"],
                },
                "mcp": {
                    "name": name,
                    "description": spec.get("description", ""),
                    "inputSchema": input_schema,
                    "annotations": {"readOnlyHint": True, "destructiveHint": False},
                },
            }
            tools.append(item)
            mcp_tools.append(item["mcp"])
        return {
            "registry": "complaint-copilot-tool-registry",
            "version": "0.1.0",
            "protocol": "mcp-lite-json-rpc",
            "role": role,
            "tools": tools,
            "mcp": {"tools": mcp_tools},
        }

    def invoke(self, tool_name: str, arguments: dict[str, Any] | None = None, role: str = "analyst") -> dict[str, Any]:
        specs = self._tool_specs()
        if tool_name not in specs:
            return {"error": {"code": "unknown_tool", "message": f"Tool {tool_name} is not registered."}}
        required_permission = self.TOOL_PERMISSIONS.get(tool_name, "data:query")
        if required_permission not in PermissionPolicy.permissions_for(role):
            return {
                "error": {
                    "code": "permission_denied",
                    "message": f"Role {role} lacks {required_permission} for tool {tool_name}.",
                }
            }
        try:
            validated_args = self.function_agent._validate_tool_args(tool_name, arguments or {})
            result, duration_ms = timed_call(self.function_agent._execute_tool, tool_name, validated_args)
        except (ValidationError, ValueError) as exc:
            return {"error": {"code": "invalid_tool_arguments", "message": str(exc)}}
        return {
            "tool": tool_name,
            "arguments": validated_args,
            "result": result,
            "tool_trace": [{
                "tool": tool_name,
                "arguments": validated_args,
                "duration_ms": duration_ms,
                "result_summary": summarize_text(json.dumps(result, ensure_ascii=False), limit=180),
            }],
            "safety": {
                "read_only": True,
                "required_permission": required_permission,
                "role": role,
            },
        }

    def handle_mcp(self, envelope: dict[str, Any], role: str = "analyst") -> dict[str, Any]:
        request_id = envelope.get("id")
        method = envelope.get("method")
        params = envelope.get("params") or {}
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": self.list_tools(role=role)["mcp"],
            }
        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            call_result = self.invoke(str(tool_name or ""), arguments=arguments, role=role)
            if call_result.get("error"):
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": call_result["error"]["message"], "data": call_result["error"]},
                }
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(call_result["result"], ensure_ascii=False)}],
                    "structuredContent": call_result["result"],
                    "tool_trace": call_result["tool_trace"],
                },
            }
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Unsupported MCP method: {method}"},
        }
