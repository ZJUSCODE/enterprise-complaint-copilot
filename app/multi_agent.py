from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, TypedDict

from app.domain import contains_any, detect_category_from_query, POLICY_PATTERNS, QUERY_PATTERNS

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:
    END = "__end__"
    START = "__start__"
    StateGraph = None


class SupervisorState(TypedDict, total=False):
    message: str
    session_id: str | None
    request_id: str
    start_time: float
    agents_to_call: list[str]
    agents_completed: list[str]
    data_result: dict[str, Any]
    policy_result: dict[str, Any]
    risk_result: dict[str, Any]
    response: dict[str, Any]
    graph_trace: list[str]


AGENT_PATTERNS = {
    "data": ["明细", "统计", "查询", "退款", "赔付", "金额", "数量", "超过", "最多", "top", "query", "statistics", "count", "refund", "compensation"],
    "policy": ["SOP", "政策", "规则", "处理", "应该", "怎么", "流程", "依据", "复核", "升级", "policy", "rule", "guidance", "procedure"],
    "risk": ["风险", "风险分", "风险等级", "用户", "risk", "user risk"],
}


class SupervisorAgent:
    def __init__(self, orchestrator: Any):
        self.orchestrator = orchestrator
        self.graph = self._build_graph() if StateGraph else None

    def _with_trace(self, state: SupervisorState, node_name: str, **updates: Any) -> SupervisorState:
        return {**state, **updates, "graph_trace": [*state.get("graph_trace", []), node_name]}

    def _classify_agents(self, message: str) -> list[str]:
        msg_lower = message.lower()
        agents = []
        for agent, patterns in AGENT_PATTERNS.items():
            if contains_any(message, patterns) or any(p in msg_lower for p in patterns):
                agents.append(agent)
        if not agents:
            agents = ["data"]
        return agents

    def _supervisor_node(self, state: SupervisorState) -> SupervisorState:
        agents = self._classify_agents(state["message"])
        return self._with_trace(state, "supervisor_node", agents_to_call=agents, agents_completed=[])

    def _data_agent_node(self, state: SupervisorState) -> SupervisorState:
        message = state["message"]
        result = self.orchestrator.function_agent.respond(message, session_id=state.get("session_id"))
        completed = state.get("agents_completed", []) + ["data"]
        return self._with_trace(state, "data_agent_node", data_result=result, agents_completed=completed)

    def _policy_agent_node(self, state: SupervisorState) -> SupervisorState:
        message = state["message"]
        cat = detect_category_from_query(message)
        if self.orchestrator.langchain_rag and self.orchestrator.langchain_rag.available:
            rag_result = self.orchestrator.langchain_rag.query(message, category=cat, top_k=3)
            result = {
                "citations": [{"label": s["citation"], "text": s["excerpt"], "retrieval_score": s.get("retrieval_score"), "rerank_score": s.get("rerank_score"), "source": s.get("source"), "rrf_score": s.get("rrf_score")} for s in rag_result.get("sources", [])],
                "answer": rag_result.get("answer", ""),
                "tool_trace": [{"tool": "langchain_rag", "arguments": {"query": message, "category": cat}, "duration_ms": rag_result.get("total_ms", 0)}],
            }
        else:
            docs = self.orchestrator.knowledge_base.lexical_search(message, category=cat, top_k=3)
            result = {
                "citations": [{"label": d["citation"], "text": d["excerpt"], "source": "lexical"} for d in docs],
                "answer": "；".join(d.get("guidance", [d["title"]])[:2] for d in docs[:1]) or "未命中明确 SOP。",
                "tool_trace": [{"tool": "lexical_search", "arguments": {"query": message, "category": cat}}],
            }
        completed = state.get("agents_completed", []) + ["policy"]
        return self._with_trace(state, "policy_agent_node", policy_result=result, agents_completed=completed)

    def _risk_agent_node(self, state: SupervisorState) -> SupervisorState:
        user_match = re.search(r"[0-9a-f]{24,}", state["message"], re.IGNORECASE)
        if user_match:
            result = self.orchestrator.analytics.get_user_risk(user_match.group(0))
        else:
            result = {"found": False, "message": "未识别到用户 ID。"}
        completed = state.get("agents_completed", []) + ["risk"]
        return self._with_trace(state, "risk_agent_node", risk_result=result, agents_completed=completed)

    def _synthesis_node(self, state: SupervisorState) -> SupervisorState:
        agents = state.get("agents_to_call", [])
        data_result = state.get("data_result") or {}
        policy_result = state.get("policy_result") or {}
        risk_result = state.get("risk_result") or {}

        highlights: list[str] = []
        citations: list[dict[str, Any]] = []
        tool_trace: list[dict[str, Any]] = []
        summary_parts: list[str] = []
        metrics: list[dict[str, Any]] = []
        table: list[dict[str, Any]] = []
        sql_preview: str | None = None

        if "data" in agents and data_result:
            summary_parts.append(f"数据查询：{data_result.get('summary', '已完成')}")
            highlights.extend(data_result.get("highlights", [])[:2])
            tool_trace.extend(data_result.get("tool_trace", []))
            metrics.extend(data_result.get("metrics", []))
            table.extend(data_result.get("table", []))
            sql_preview = data_result.get("sql_preview") or sql_preview

        if "policy" in agents and policy_result:
            summary_parts.append(f"政策检索：{policy_result.get('answer', '已完成')}")
            citations.extend(policy_result.get("citations", []))
            tool_trace.extend(policy_result.get("tool_trace", []))
            highlights.extend([c.get("label", "") for c in policy_result.get("citations", [])[:2]])

        if "risk" in agents and risk_result:
            if risk_result.get("found"):
                summary_parts.append(f"风险评估：用户风险分 {risk_result.get('risk_score')}，等级 {risk_result.get('risk_level')}")
                highlights.extend([f"风险分：{risk_result.get('risk_score')}", f"风险等级：{risk_result.get('risk_level')}"])
            else:
                summary_parts.append(f"风险评估：{risk_result.get('message', '未找到用户记录')}")

        summary = "多智能体协同完成：\n" + "\n".join(summary_parts) if summary_parts else "未执行任何子任务。"
        agent_dispatch = [{"agent": a, "called": True} for a in agents]

        response: dict[str, Any] = {
            "mode": "multi_agent",
            "title": "多智能体协同",
            "summary": summary,
            "highlights": highlights[:6],
            "citations": citations,
            "tool_trace": tool_trace,
            "agent_dispatch": agent_dispatch,
        }
        if metrics:
            response["metrics"] = metrics
        if table:
            response["table"] = table
        if sql_preview:
            response["sql_preview"] = sql_preview
        return self._with_trace(state, "synthesis_node", response=response)

    # ── Conditional routing functions ──

    def _should_run_data(self, state: SupervisorState) -> bool:
        return "data" in state.get("agents_to_call", [])

    def _should_run_policy(self, state: SupervisorState) -> bool:
        return "policy" in state.get("agents_to_call", [])

    def _should_run_risk(self, state: SupervisorState) -> bool:
        return "risk" in state.get("agents_to_call", [])

    def _route_after_supervisor(self, state: SupervisorState) -> str:
        """Route to the first relevant agent, or synthesis if none."""
        agents = state.get("agents_to_call", [])
        if "data" in agents:
            return "data_agent_node"
        if "policy" in agents:
            return "policy_agent_node"
        if "risk" in agents:
            return "risk_agent_node"
        return "synthesis_node"

    def _route_after_data(self, state: SupervisorState) -> str:
        """After data agent, go to policy if needed, else risk if needed, else synthesis."""
        agents = state.get("agents_to_call", [])
        if "policy" in agents:
            return "policy_agent_node"
        if "risk" in agents:
            return "risk_agent_node"
        return "synthesis_node"

    def _route_after_policy(self, state: SupervisorState) -> str:
        """After policy agent, go to risk if needed, else synthesis."""
        agents = state.get("agents_to_call", [])
        if "risk" in agents:
            return "risk_agent_node"
        return "synthesis_node"

    def _build_graph(self):
        graph = StateGraph(SupervisorState)
        graph.add_node("supervisor_node", self._supervisor_node)
        graph.add_node("data_agent_node", self._data_agent_node)
        graph.add_node("policy_agent_node", self._policy_agent_node)
        graph.add_node("risk_agent_node", self._risk_agent_node)
        graph.add_node("synthesis_node", self._synthesis_node)

        graph.add_edge(START, "supervisor_node")

        # Conditional edges: supervisor routes to first relevant agent
        graph.add_conditional_edges(
            "supervisor_node",
            self._route_after_supervisor,
            {
                "data_agent_node": "data_agent_node",
                "policy_agent_node": "policy_agent_node",
                "risk_agent_node": "risk_agent_node",
                "synthesis_node": "synthesis_node",
            },
        )

        # Conditional edges: each agent routes to next relevant agent or synthesis
        graph.add_conditional_edges(
            "data_agent_node",
            self._route_after_data,
            {
                "policy_agent_node": "policy_agent_node",
                "risk_agent_node": "risk_agent_node",
                "synthesis_node": "synthesis_node",
            },
        )

        graph.add_conditional_edges(
            "policy_agent_node",
            self._route_after_policy,
            {
                "risk_agent_node": "risk_agent_node",
                "synthesis_node": "synthesis_node",
            },
        )

        graph.add_edge("risk_agent_node", "synthesis_node")
        graph.add_edge("synthesis_node", END)
        return graph.compile()

    def coordinate(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        if not self.graph:
            return self._coordinate_without_graph(message, session_id)
        result = self.graph.invoke({
            "message": message,
            "session_id": session_id,
            "request_id": str(uuid.uuid4()),
            "start_time": time.perf_counter(),
            "graph_trace": [],
        })
        response = result.get("response") or {}
        response["graph_trace"] = result.get("graph_trace", [])
        response["graph_engine"] = "langgraph"
        return response

    def _coordinate_without_graph(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        agents = self._classify_agents(message)
        state: SupervisorState = {
            "message": message,
            "session_id": session_id,
            "agents_to_call": agents,
            "agents_completed": [],
            "request_id": str(uuid.uuid4()),
            "start_time": time.perf_counter(),
            "graph_trace": ["supervisor_node"],
        }
        if "data" in agents:
            state = self._data_agent_node(state)
        if "policy" in agents:
            state = self._policy_agent_node(state)
        if "risk" in agents:
            state = self._risk_agent_node(state)
        state = self._synthesis_node(state)
        response = state.get("response") or {}
        response["graph_trace"] = state.get("graph_trace", [])
        response["graph_engine"] = "direct"
        return response
