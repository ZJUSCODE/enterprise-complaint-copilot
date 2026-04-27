from __future__ import annotations

import time
import uuid
from typing import Any, TypedDict

from app.permissions import PermissionPolicy

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover - optional dependency fallback
    END = "__end__"
    START = "__start__"
    StateGraph = None


class LangGraphAgentState(TypedDict, total=False):
    message: str
    requested_mode: str
    route_mode: str
    role: str
    session_id: str | None
    request_id: str
    start_time: float
    route: dict[str, Any]
    response: dict[str, Any]
    graph_trace: list[str]


class LangGraphWorkflow:
    def __init__(self, orchestrator: Any):
        self.orchestrator = orchestrator
        self.graph = self._build_graph() if StateGraph else None

    def _with_trace(self, state: LangGraphAgentState, node_name: str, **updates: Any) -> LangGraphAgentState:
        return {**updates, "graph_trace": [*state.get("graph_trace", []), node_name]}

    def _permission_node(self, state: LangGraphAgentState) -> LangGraphAgentState:
        requested_mode = state.get("requested_mode", "function_call_agent")
        role = state.get("role", "analyst")
        if not PermissionPolicy.can_use_mode(role, requested_mode):
            response = {
                "mode": "permission_denied",
                "title": "权限不足",
                "summary": f"当前角色 {role} 无权使用 {requested_mode} 工作流。",
                "highlights": [
                    "LangGraph permission_node 已拦截本次请求。",
                    "viewer 只能查询政策类 RAG",
                    "analyst / supervisor 可使用只读数据查询",
                ],
                "tool_trace": [],
            }
            return self._with_trace(state, "permission_node", response=response)
        return self._with_trace(state, "permission_node")

    def _guardrail_node(self, state: LangGraphAgentState) -> LangGraphAgentState:
        if state.get("response"):
            return self._with_trace(state, "guardrail_node")
        blocked = self.orchestrator.function_agent._guardrail(state["message"])
        if blocked:
            return self._with_trace(state, "guardrail_node", response=blocked)
        return self._with_trace(state, "guardrail_node")

    def _router_node(self, state: LangGraphAgentState) -> LangGraphAgentState:
        if state.get("response"):
            return self._with_trace(state, "router_node")
        requested_mode = state.get("requested_mode", "function_call_agent")
        if requested_mode in {"auto", "router_demo"}:
            route = self.orchestrator.router.route(state["message"])
            return self._with_trace(state, "router_node", route=route, route_mode=route["mode"])
        route = {"mode": requested_mode, "reason": "LangGraph 使用用户指定工作流。", "confidence": 1.0, "source": "explicit_mode"}
        return self._with_trace(state, "router_node", route=route, route_mode=requested_mode)

    def _execute_node(self, state: LangGraphAgentState) -> LangGraphAgentState:
        if state.get("response"):
            return self._with_trace(state, "execute_node")
        route_mode = state.get("route_mode") or state.get("requested_mode", "function_call_agent")
        response = self.orchestrator._respond_impl(state["message"], route_mode, session_id=state.get("session_id"))
        response.setdefault("highlights", [])
        response["highlights"] = [
            f"LangGraph route: {route_mode}",
            *response["highlights"],
        ]
        if state.get("route"):
            response["route"] = state["route"]
        return self._with_trace(state, "execute_node", response=response)

    def _review_node(self, state: LangGraphAgentState) -> LangGraphAgentState:
        response = dict(state.get("response") or {})
        if response.get("review_required") and not response.get("review_case"):
            response["review_case"] = self.orchestrator.review_queue.enqueue({
                "request_id": state["request_id"],
                "session_id": response.get("session_id") or state.get("session_id"),
                "user_role": state.get("role", "analyst"),
                "source_mode": response.get("mode", state.get("route_mode", state.get("requested_mode", "function_call_agent"))),
                "reason": response.get("review_reason", "需要人工复核"),
                "user_message": state["message"],
                "response_summary": response.get("summary"),
                "tool_trace": response.get("tool_trace", []),
            })
        return self._with_trace(state, "review_node", response=response)

    def _audit_node(self, state: LangGraphAgentState) -> LangGraphAgentState:
        response = dict(state.get("response") or {})
        request_id = state["request_id"]
        latency_ms = round((time.perf_counter() - state["start_time"]) * 1000, 2)
        response["request_id"] = request_id
        response["latency_ms"] = latency_ms
        response["graph_trace"] = [*state.get("graph_trace", []), "audit_node"]
        response["graph_engine"] = "langgraph"
        if state.get("route") and not response.get("route"):
            response["route"] = state["route"]
        self.orchestrator.audit_log.record({
            "request_id": request_id,
            "session_id": response.get("session_id") or state.get("session_id"),
            "mode": response.get("mode", state.get("route_mode", state.get("requested_mode", "function_call_agent"))),
            "route": response.get("route"),
            "blocked_by_guardrail": response.get("mode") == "guardrail",
            "blocked_by_permission": response.get("mode") == "permission_denied",
            "user_role": state.get("role", "analyst"),
            "user_message": state["message"],
            "response_title": response.get("title"),
            "tool_trace": response.get("tool_trace", []),
            "sql_preview": response.get("sql_preview"),
            "latency_ms": latency_ms,
        })
        return self._with_trace(state, "audit_node", response=response)

    def _after_permission(self, state: LangGraphAgentState) -> str:
        return "audit_node" if state.get("response") else "guardrail_node"

    def _after_guardrail(self, state: LangGraphAgentState) -> str:
        if not state.get("response"):
            return "router_node"
        return "review_node" if state["response"].get("review_required") else "audit_node"

    def _after_execute(self, state: LangGraphAgentState) -> str:
        return "review_node" if state.get("response", {}).get("review_required") else "audit_node"

    def _build_graph(self):
        graph = StateGraph(LangGraphAgentState)
        graph.add_node("permission_node", self._permission_node)
        graph.add_node("guardrail_node", self._guardrail_node)
        graph.add_node("router_node", self._router_node)
        graph.add_node("execute_node", self._execute_node)
        graph.add_node("review_node", self._review_node)
        graph.add_node("audit_node", self._audit_node)
        graph.add_edge(START, "permission_node")
        graph.add_conditional_edges("permission_node", self._after_permission)
        graph.add_conditional_edges("guardrail_node", self._after_guardrail)
        graph.add_edge("router_node", "execute_node")
        graph.add_conditional_edges("execute_node", self._after_execute)
        graph.add_edge("review_node", "audit_node")
        graph.add_edge("audit_node", END)
        return graph.compile()

    def respond(self, message: str, mode: str, session_id: str | None = None, role: str = "analyst") -> dict[str, Any]:
        if not self.graph:
            response = self.orchestrator.respond(message, mode=mode, session_id=session_id, role=role)
            response["graph_engine"] = "unavailable"
            response["graph_trace"] = ["langgraph_missing", "orchestrator_fallback"]
            return response
        result = self.graph.invoke({
            "message": message,
            "requested_mode": mode,
            "role": role,
            "session_id": session_id,
            "request_id": str(uuid.uuid4()),
            "start_time": time.perf_counter(),
            "graph_trace": [],
        })
        return result["response"]
