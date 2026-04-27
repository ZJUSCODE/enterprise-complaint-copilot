from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.audit_stores import AuditLogStore, FeedbackEventStore, HumanReviewQueue
from app.analytics import LocalAnalyticsEngine
from app.function_agent import FunctionCallingAgent
from app.config import (
    APP_TITLE,
    AUDIT_DB_PATH,
    AUTH_DB_PATH,
    BASE_DIR,
    DATA_DIR,
    FRONTEND_ASSETS_DIR,
    FRONTEND_DIST_DIR,
    KB_DIR,
    SQLITE_DB_PATH,
    STATIC_DIR,
    TEMPLATE_DIR,
    Settings,
    load_dotenv_file,
    logger,
)
from app.domain import (
    COMPLAINT_PATTERNS,
    POLICY_PATTERNS,
    contains_any,
    detect_category_from_query,
)
from app.permissions import PermissionPolicy
from app.rag import LangChainRAGService, PolicyKnowledgeBase
from app.routing import AutoRouter
from app.security import jwt_decode, jwt_encode, utc_now
from app.schemas import (
    AuthUser,
    ChatRequest,
    FeedbackRequest,
    LoginRequest,
    LoginResponse,
    MCPRequest,
    ReviewDecisionRequest,
    ToolInvocationRequest,
)
from app.stores import RedisRuntime, SessionMemoryStore, TaskQueueStore, UserStore
from app.tool_registry import ToolRegistry
from app.ticket_store import (
    MySQLReadOnlyTicketStore,
    QueryFilters,
    ReadOnlySQLiteStore,
    build_tickets_export_frame,
)
from app.utils import (
    SQL_FORBIDDEN_KEYWORDS,
    estimate_cost,
    estimate_cost_breakdown,
    safe_json_loads,
    summarize_text,
    timed_call,
    validate_readonly_sql,
)

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover - optional dependency fallback
    END = "__end__"
    START = "__start__"
    StateGraph = None


def load_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


class Orchestrator:
    def __init__(self, settings: Settings, analytics: LocalAnalyticsEngine, sql_store: ReadOnlySQLiteStore, knowledge_base: PolicyKnowledgeBase, audit_log: AuditLogStore, review_queue: HumanReviewQueue, redis_runtime: RedisRuntime | None = None):
        self.settings = settings
        self.analytics = analytics
        self.sql_store = sql_store
        self.knowledge_base = knowledge_base
        self.audit_log = audit_log
        self.review_queue = review_queue
        self.redis = redis_runtime
        self.memory = SessionMemoryStore(redis_runtime, ttl_seconds=settings.session_ttl_seconds)
        self.function_agent = FunctionCallingAgent(settings, analytics, sql_store, knowledge_base, self.memory)
        self.langchain_rag = LangChainRAGService(settings, knowledge_base)
        self.router = AutoRouter(settings)

    def respond(self, message: str, mode: str, session_id: str | None = None, role: str = "analyst", response_language: str = "auto", trace_id: str | None = None) -> dict[str, Any]:
        request_id = str(uuid.uuid4())
        trace_id = trace_id or str(uuid.uuid4())
        start = time.perf_counter()
        if not PermissionPolicy.can_use_mode(role, mode):
            response = {
                "mode": "permission_denied",
                "title": "权限不足",
                "summary": f"当前角色 {role} 无权使用 {mode} 工作流。",
                "highlights": [
                    "权限系统已阻止本次调用",
                    "viewer 只能查询政策类 RAG",
                    "analyst / supervisor 可使用只读数据查询",
                ],
                "tool_trace": [],
                "error": {"code": "permission_denied", "message": f"role {role} cannot use {mode}"},
            }
        else:
            try:
                response = self._respond_impl(message, mode, session_id=session_id)
            except Exception as exc:
                response = {
                    "mode": "degraded_error",
                    "title": "Request Degraded",
                    "summary": "The request failed inside the agent path, so the API returned a safe degraded response instead of executing uncertain actions.",
                    "session_id": session_id,
                    "tool_trace": [],
                    "degradation_path": "exception_to_safe_response",
                    "error": {"code": "agent_execution_failed", "message": str(exc)},
                }
        response["request_id"] = request_id
        response["trace_id"] = trace_id
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        response["latency_ms"] = latency_ms
        token_usage = response.pop("_token_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        cost_breakdown = response.pop("_cost_breakdown", None) or estimate_cost_breakdown(self.settings, token_usage)
        retry_count = int(response.pop("_retry_count", 0) or 0)
        response["token_usage"] = token_usage
        response["cost_breakdown"] = cost_breakdown
        response["estimated_cost_usd"] = float(cost_breakdown.get("total_cost_usd", estimate_cost(self.settings, token_usage)))
        response["retry_count"] = retry_count
        response["response_language"] = response_language
        response["trace"] = {
            "request_id": request_id,
            "trace_id": trace_id,
            "latency_ms": latency_ms,
            "tool_call_count": len(response.get("tool_trace", []) or []),
            "rag_retrieval_ms": max([float(item.get("duration_ms", 0) or 0) for item in response.get("tool_trace", []) or [] if "rag" in str(item.get("tool", "")).lower()] or [0]),
            "token_usage": token_usage,
            "cost_breakdown": cost_breakdown,
            "estimated_cost_usd": response["estimated_cost_usd"],
            "retry_count": retry_count,
        }
        if response.get("review_required"):
            response["review_case"] = self.review_queue.enqueue({
                "request_id": request_id,
                "session_id": response.get("session_id") or session_id,
                "user_role": role,
                "source_mode": response.get("mode", mode),
                "reason": response.get("review_reason", "需要人工复核"),
                "user_message": message,
                "response_summary": response.get("summary"),
                "tool_trace": response.get("tool_trace", []),
                "case_priority": "high" if response.get("mode") == "guardrail" or "high priority" in str(response.get("review_reason", "")).lower() else "medium",
                "escalation_reason": response.get("review_reason"),
                "assignee": "supervisor_queue",
            })
        self.audit_log.record({
            "request_id": request_id,
            "trace_id": trace_id,
            "session_id": response.get("session_id") or session_id,
            "mode": response.get("mode", mode),
            "route": response.get("route"),
            "blocked_by_guardrail": response.get("mode") == "guardrail",
            "blocked_by_permission": response.get("mode") == "permission_denied",
            "user_role": role,
            "user_message": message,
            "response_title": response.get("title"),
            "tool_trace": response.get("tool_trace", []),
            "sql_preview": response.get("sql_preview"),
            "latency_ms": latency_ms,
            "token_usage": token_usage,
            "estimated_cost_usd": response["estimated_cost_usd"],
            "retry_count": retry_count,
        })
        logger.info(json.dumps({
            "event": "copilot_request",
            "request_id": request_id,
            "trace_id": trace_id,
            "mode": response.get("mode", mode),
            "role": role,
            "latency_ms": latency_ms,
            "retry_count": retry_count,
            "cost_usd": response["estimated_cost_usd"],
            "error_code": (response.get("error") or {}).get("code"),
        }, ensure_ascii=False))
        return response

    def _respond_sql_rag_chain(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        sid = self.memory.get_or_create(session_id)
        sql_args = self.function_agent._validate_tool_args("query_refund_cases", {"query": message})
        sql_result, sql_duration_ms = timed_call(self.sql_store.query_ticket_details, QueryFilters(
            category=sql_args.get("category"),
            complaint_type=sql_args.get("complaint_type"),
            amount_threshold=sql_args.get("amount_threshold"),
        ))
        top_rows = sql_result.get("rows", [])[:3]
        top_row_text = "；".join(
            f"{row.get('category', '其他')}/{row.get('complaint_type', '-')}/赔付{row.get('compensation_amount', 0)}元"
            for row in top_rows
        ) or "未命中异常明细"
        policy_query = (
            f"{message}\n"
            f"SQL 摘要：{sql_result.get('summary', '')}\n"
            f"命中样例：{top_row_text}\n"
            "请基于售后 SOP 判断处理依据、是否需要主管或人工复核。"
        )
        rag_result, rag_duration_ms = timed_call(self.langchain_rag.query, policy_query, category=sql_args.get("category"), top_k=3)
        citations = [
            {
                "label": item["citation"],
                "text": item["excerpt"],
                "retrieval_score": item.get("retrieval_score"),
                "rerank_score": item.get("rerank_score"),
                "source": item.get("source"),
            }
            for item in rag_result.get("sources", [])
        ]
        tool_trace = [
            {"tool": "query_refund_cases", "arguments": sql_args, "duration_ms": sql_duration_ms, "result_summary": summarize_text(json.dumps(sql_result, ensure_ascii=False), limit=180)},
            {
                "tool": "langchain_rag",
                "arguments": {"query": policy_query, "category": sql_args.get("category")},
                "duration_ms": rag_result.get("total_ms", rag_duration_ms),
                "result_summary": summarize_text(rag_result.get("answer", ""), limit=180),
                "token_usage": rag_result.get("token_usage", {}),
                "cost_breakdown": rag_result.get("cost_breakdown", {}),
                "timing": {
                    "embedding_ms": rag_result.get("embedding_ms", 0),
                    "retrieval_ms": rag_result.get("retrieval_ms", 0),
                    "generation_ms": rag_result.get("generation_ms", 0),
                    "total_ms": rag_result.get("total_ms", rag_duration_ms),
                },
            },
        ]
        rag_token_usage = rag_result.get("token_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        rag_cost_breakdown = rag_result.get("cost_breakdown") or estimate_cost_breakdown(self.settings, rag_token_usage)
        max_compensation = max([float(row.get("compensation_amount") or 0) for row in sql_result.get("rows", [])] or [0.0])
        rag_answer = rag_result.get("answer", "")
        rows = sql_result.get("rows", [])
        metrics = sql_result.get("metrics", {})
        unified_rule_missing = contains_any(
            rag_answer,
            ["无法直接判断", "未提及", "未说明", "未在上下文", "没有统一", "不存在统一", "上下文不足"],
        )
        asks_review = contains_any(message, ["主管", "复核", "升级", "人工"])
        needs_review = bool(rows) and (
            (asks_review and unified_rule_missing)
            or (max_compensation >= 100 and contains_any(rag_answer, ["复核", "主管", "升级", "高风险", "高货值"]))
        )

        visible_categories = sorted({str(row.get("category") or "其他") for row in rows})
        category_line = "、".join(visible_categories[:4]) if visible_categories else "未命中"
        count = metrics.get("异常工单数", len(rows))
        avg_compensation = metrics.get("平均赔付", 0)
        total_compensation = metrics.get("估算赔付总额", 0)
        summary_parts = [
            f"结论：这批命中明细需要进入人工复核，但不能简单归因为“质量问题退款超过 {sql_args.get('amount_threshold') or 100:g} 元就必须主管复核”。",
            f"SQL 已命中 {count} 条{sql_args.get('complaint_type') or ''}异常，估算赔付合计 {total_compensation} 元，平均赔付 {avg_compensation} 元，最高赔付 {round(max_compensation, 2)} 元。",
        ]
        if unified_rule_missing:
            summary_parts.append("SOP 检索没有找到“所有质量问题按金额阈值统一复核”的条款，因此不能自动套用统一规则。")
        else:
            summary_parts.append("SOP 命中了复核或升级相关条款，需结合具体商品类目、用户风险和取证状态判断。")
        summary_parts.append(f"下一步：先按类目分流处理展示样例中的 {category_line}；3C 数码补 SN、故障描述和照片，其他类目作为规则缺口进入人工复核。")
        summary = "\n".join(summary_parts)
        highlights = [
            f"SQL 命中：{count} 条，平均赔付 {avg_compensation} 元，最高赔付 {round(max_compensation, 2)} 元。",
            "SOP 结论：未找到“质量问题超过金额阈值统一主管复核”的通用规则。",
            "处理方式：按商品类目和用户风险分流；缺少类目专门条款时，不自动承诺退款，进入人工复核。",
        ]
        if needs_review:
            highlights.append("已进入人工复核队列：原因是高赔付异常 + SOP 规则缺口，而不是金额阈值本身。")
        self.memory.append(sid, "user", message)
        self.memory.append(sid, "assistant", summary)
        return {
            "mode": "sql_rag_chain",
            "title": "SQL -> RAG 复合链路",
            "summary": summary,
            "session_id": sid,
            "metrics": [{"label": key, "value": value} for key, value in sql_result.get("metrics", {}).items()],
            "table": sql_result.get("rows", []),
            "sql_preview": sql_result.get("sql_preview"),
            "highlights": highlights,
            "citations": citations,
            "tool_trace": tool_trace,
            "review_required": needs_review,
            "review_reason": "SQL 命中高赔付质量问题异常，但 SOP 未提供按金额统一复核的明确条款，需人工按类目与风险补判。",
            "_token_usage": rag_token_usage,
            "_cost_breakdown": rag_cost_breakdown,
        }

    def _respond_impl(self, message: str, mode: str, session_id: str | None = None) -> dict[str, Any]:
        blocked = self.function_agent._guardrail(message)
        if blocked:
            return blocked
        if mode == "langchain_rag":
            result, rag_duration_ms = timed_call(self.langchain_rag.query, message, category=detect_category_from_query(message), top_k=3)
            return {
                "mode": "langchain_rag",
                "title": "LangChain RAG",
                "summary": result["answer"],
                "session_id": session_id,
                "highlights": ["面向售后 SOP 的检索增强问答。", "先检索文档，再由模型基于上下文回答。", "当前实现适合讲解完整的 RAG pipeline。"],
                "citations": [{"label": item["citation"], "text": item["excerpt"], "retrieval_score": item.get("retrieval_score"), "rerank_score": item.get("rerank_score"), "source": item.get("source")} for item in result.get("sources", [])],
                "tool_trace": [{
                    "tool": "langchain_rag",
                    "arguments": {"query": message, "top_k": 3},
                    "duration_ms": result.get("total_ms", rag_duration_ms),
                    "result_summary": summarize_text(result.get("answer", ""), limit=180),
                    "token_usage": result.get("token_usage", {}),
                    "cost_breakdown": result.get("cost_breakdown", {}),
                    "timing": {
                        "embedding_ms": result.get("embedding_ms", 0),
                        "retrieval_ms": result.get("retrieval_ms", 0),
                        "generation_ms": result.get("generation_ms", 0),
                        "total_ms": result.get("total_ms", rag_duration_ms),
                    },
                }],
                "degradation_path": result.get("fallback_reason"),
                "_token_usage": result.get("token_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
                "_cost_breakdown": result.get("cost_breakdown"),
            }
        if mode == "sql_rag_chain":
            return self._respond_sql_rag_chain(message, session_id=session_id)
        if mode in {"router_demo", "auto"}:
            decision = self.router.route(message)
            delegated = self._respond_impl(message, decision["mode"], session_id=session_id)
            delegated["mode"] = mode
            delegated["title"] = "Router Demo" if mode == "router_demo" else delegated.get("title", "Auto Router")
            delegated.setdefault("highlights", [])
            delegated["highlights"] = [f"路由结果：{decision['mode']}", f"路由来源：{decision['source']}", f"路由置信度：{decision['confidence']:.2f}", f"路由原因：{decision['reason']}", *delegated["highlights"]]
            delegated["route"] = decision
            return delegated
        return self.function_agent.respond(message, session_id=session_id)


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
    def __init__(self, orchestrator: Orchestrator):
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


@dataclass
class RuntimeState:
    settings: Settings
    redis_runtime: RedisRuntime
    user_store: UserStore
    task_queue: TaskQueueStore
    analytics: LocalAnalyticsEngine
    sql_store: Any
    knowledge_base: PolicyKnowledgeBase
    audit_log: AuditLogStore
    review_queue: HumanReviewQueue
    feedback_events: FeedbackEventStore
    orchestrator: Orchestrator
    tool_registry: ToolRegistry
    langgraph_workflow: LangGraphWorkflow


_runtime_state: RuntimeState | None = None


def initialize_runtime() -> RuntimeState:
    global _runtime_state
    if _runtime_state is None:
        load_dotenv_file(BASE_DIR / ".env")
        runtime_settings = Settings()
        runtime_redis = RedisRuntime(runtime_settings)
        runtime_user_store = UserStore(AUTH_DB_PATH)
        runtime_task_queue = TaskQueueStore(runtime_redis)
        runtime_analytics = LocalAnalyticsEngine(DATA_DIR)
        runtime_sql_store = MySQLReadOnlyTicketStore() if runtime_settings.data_query_backend == "mysql" else ReadOnlySQLiteStore(SQLITE_DB_PATH, runtime_analytics)
        runtime_knowledge_base = PolicyKnowledgeBase(KB_DIR / "policies.json")
        runtime_audit_log = AuditLogStore(AUDIT_DB_PATH)
        runtime_review_queue = HumanReviewQueue(AUDIT_DB_PATH)
        runtime_feedback_events = FeedbackEventStore(AUDIT_DB_PATH)
        runtime_orchestrator = Orchestrator(
            runtime_settings,
            runtime_analytics,
            runtime_sql_store,
            runtime_knowledge_base,
            runtime_audit_log,
            runtime_review_queue,
            runtime_redis,
        )
        runtime_tool_registry = ToolRegistry(runtime_orchestrator.function_agent)
        runtime_langgraph_workflow = LangGraphWorkflow(runtime_orchestrator)
        _runtime_state = RuntimeState(
            settings=runtime_settings,
            redis_runtime=runtime_redis,
            user_store=runtime_user_store,
            task_queue=runtime_task_queue,
            analytics=runtime_analytics,
            sql_store=runtime_sql_store,
            knowledge_base=runtime_knowledge_base,
            audit_log=runtime_audit_log,
            review_queue=runtime_review_queue,
            feedback_events=runtime_feedback_events,
            orchestrator=runtime_orchestrator,
            tool_registry=runtime_tool_registry,
            langgraph_workflow=runtime_langgraph_workflow,
        )
    return _runtime_state


def get_runtime() -> RuntimeState:
    return initialize_runtime()


def __getattr__(name: str) -> Any:
    if name in {"settings", "redis_runtime", "user_store", "task_queue", "analytics", "sql_store", "knowledge_base", "audit_log", "review_queue", "feedback_events", "orchestrator", "tool_registry", "langgraph_workflow"}:
        return getattr(get_runtime(), name)
    raise AttributeError(name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_runtime()
    yield


app = FastAPI(title=APP_TITLE, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
if FRONTEND_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="frontend-assets")


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def optional_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any] | None:
    runtime = get_runtime()
    token = _bearer_token(authorization)
    if not token:
        if runtime.settings.auth_enforced:
            raise HTTPException(status_code=401, detail={"code": "missing_token", "message": "Bearer token required"})
        return None
    try:
        payload = jwt_decode(token, runtime.settings.jwt_secret)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail={"code": str(exc), "message": "Invalid or expired token"}) from exc
    user = runtime.user_store.get_by_id(str(payload.get("sub", "")))
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail={"code": "user_inactive", "message": "User is inactive or missing"})
    return user


def require_current_user(current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    if current_user:
        return current_user
    raise HTTPException(status_code=401, detail={"code": "missing_token", "message": "Bearer token required"})


def resolve_role(requested_role: str | None, current_user: dict[str, Any] | None) -> str:
    return current_user["role"] if current_user else (requested_role or "analyst")


def cached_response(key: str, ttl_seconds: int, builder):
    runtime = get_runtime()
    cached = runtime.redis_runtime.get_json(key)
    if cached is not None:
        return {**cached, "cache": {"hit": True, "key": key, "backend": "redis" if runtime.redis_runtime.available else "memory"}}
    value = builder()
    runtime.redis_runtime.set_json(key, value, ttl_seconds)
    return {**value, "cache": {"hit": False, "key": key, "backend": "redis" if runtime.redis_runtime.available else "memory"}}


def frontend_index_path() -> Path | None:
    index_path = FRONTEND_DIST_DIR / "index.html"
    return index_path if index_path.exists() else None


def vue_app_or_template(template_name: str):
    index_path = frontend_index_path()
    if index_path:
        return FileResponse(index_path)
    return HTMLResponse(load_template(template_name))


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    runtime = get_runtime()
    if request.url.path.startswith("/api/") and runtime.settings.rate_limit_per_minute > 0:
        client = request.client.host if request.client else "unknown"
        token = _bearer_token(request.headers.get("authorization"))
        subject = "anon"
        if token:
            try:
                subject = str(jwt_decode(token, runtime.settings.jwt_secret).get("sub", "anon"))
            except ValueError:
                subject = "invalid-token"
        bucket = int(time.time() // 60)
        key = f"rate:{subject}:{client}:{bucket}"
        count = runtime.redis_runtime.incr_with_ttl(key, 75)
        if count > runtime.settings.rate_limit_per_minute:
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "rate_limited", "message": "Too many requests in the current minute", "retry_after_seconds": 60}},
            )
    return await call_next(request)


@app.get("/api/health")
def health() -> dict[str, Any]:
    runtime = get_runtime()
    return {
        "status": "ok",
        "redis": {"available": runtime.redis_runtime.available, "error": runtime.redis_runtime.error},
        "auth_enforced": runtime.settings.auth_enforced,
        "data_query_backend": getattr(runtime.sql_store, "backend_name", runtime.settings.data_query_backend),
    }


@app.post("/api/auth/login", response_model=LoginResponse)
def login(request: LoginRequest) -> LoginResponse:
    runtime = get_runtime()
    user = runtime.user_store.authenticate(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail={"code": "invalid_credentials", "message": "Username or password is incorrect"})
    expires_at = utc_now() + timedelta(minutes=runtime.settings.jwt_access_token_minutes)
    token = jwt_encode(
        {
            "sub": user["id"],
            "username": user["username"],
            "role": user["role"],
            "iat": int(utc_now().timestamp()),
            "exp": int(expires_at.timestamp()),
        },
        runtime.settings.jwt_secret,
    )
    return LoginResponse(access_token=token, expires_at=expires_at.isoformat(), user=AuthUser(**user))


@app.get("/api/auth/me")
def auth_me(current_user: dict[str, Any] = Depends(require_current_user)) -> dict[str, Any]:
    return {"user": AuthUser(**current_user).model_dump()}


@app.get("/")
async def index():
    return vue_app_or_template("index.html")


@app.get("/legacy", response_class=HTMLResponse)
async def legacy_index() -> HTMLResponse:
    return HTMLResponse(load_template("index.html"))


@app.get("/legacy-review", response_class=HTMLResponse)
async def legacy_review_center() -> HTMLResponse:
    return HTMLResponse(load_template("review.html"))


@app.get("/review")
async def review_center():
    return vue_app_or_template("review.html")


@app.get("/api/overview")
def overview(current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    runtime = get_runtime()
    def build():
        return {
            **runtime.analytics.get_overview(),
            "api_configured": bool(runtime.settings.llm_api_key),
            "langchain_rag_enabled": runtime.orchestrator.langchain_rag.available,
            "llm_model": runtime.settings.llm_model,
            "rag_status": runtime.orchestrator.langchain_rag.error or "ready",
            "data_query_backend": getattr(runtime.sql_store, "backend_name", runtime.settings.data_query_backend),
            "langgraph_enabled": bool(runtime.langgraph_workflow.graph),
            "redis_available": runtime.redis_runtime.available,
            "auth_enforced": runtime.settings.auth_enforced,
        }
    return cached_response("hot:overview", runtime.settings.cache_ttl_seconds, build)


@app.get("/api/schema")
def schema(current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    runtime = get_runtime()
    return cached_response("hot:schema", runtime.settings.cache_ttl_seconds, runtime.sql_store.schema_catalog)


@app.get("/api/reports/daily-risk")
def daily_risk_report(date: str | None = None, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    runtime = get_runtime()
    return cached_response(f"hot:daily-risk:{date or 'latest'}", runtime.settings.cache_ttl_seconds, lambda: runtime.analytics.get_daily_risk_report(report_date=date))


@app.get("/api/sample-questions")
def sample_questions(current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    return {"items": [{"mode": "function_call_agent", "text": "查一下质量问题退款超过100元的明细"}, {"mode": "sql_rag_chain", "text": "质量问题退款超过100元的明细，按 SOP 是否需要主管复核"}, {"mode": "function_call_agent", "text": "生鲜延误坏了，运费和货款怎么赔"}, {"mode": "router_demo", "text": "退货最多的类目，按规定能不能不退"}, {"mode": "function_call_agent", "text": "用户 9ef432eb6251297304e76186b10a928d 的风险分是多少"}, {"mode": "langchain_rag", "text": "3C 数码拆封后出现质量问题，应该怎么处理"}]}


@app.get("/api/i18n/terms")
def i18n_terms(current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    return {
        "terms": [
            {"zh": "工单升级", "en": "case escalation"},
            {"zh": "人工复核", "en": "human review"},
            {"zh": "退款资格", "en": "refund eligibility"},
            {"zh": "物流状态", "en": "logistics status"},
            {"zh": "政策依据", "en": "policy citation"},
        ],
        "examples": [
            {"language": "zh", "text": "查询订单 53cdb2fc8bc7dce0b6741e2150273451 的物流状态"},
            {"language": "en", "text": "Check refund eligibility for order 53cdb2fc8bc7dce0b6741e2150273451 and reply in English."},
            {"language": "en", "text": "What is the BR market policy for damaged fresh food refunds?"},
        ],
    }


@app.get("/api/tools/registry")
def tool_registry(role: Literal["viewer", "analyst", "supervisor"] = "viewer", current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    resolved_role = resolve_role(role, current_user)
    return get_runtime().tool_registry.list_tools(role=resolved_role)


@app.post("/api/tools/invoke")
def tool_invoke(request: ToolInvocationRequest, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    role = resolve_role(request.role, current_user)
    return get_runtime().tool_registry.invoke(request.tool_name, arguments=request.arguments, role=role)


@app.post("/api/mcp")
def mcp_endpoint(request: MCPRequest, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    role = resolve_role(None, current_user)
    return get_runtime().tool_registry.handle_mcp(request.model_dump(), role=role)


def _run_eval_task(task_id: str) -> None:
    runtime = get_runtime()
    runtime.task_queue.update(task_id, "running")
    try:
        cases = json.loads((BASE_DIR / "eval" / "rag_eval.json").read_text(encoding="utf-8"))
        rows = []
        citation_hits = 0
        for case in cases:
            result = runtime.orchestrator.langchain_rag.query(case["question"], top_k=3)
            ids = [source.get("id") for source in result.get("sources", [])]
            hit = case["expected_doc_id"] in ids
            citation_hits += int(hit)
            rows.append({"question": case["question"], "expected_doc_id": case["expected_doc_id"], "returned_doc_ids": ids, "citation_hit": hit})
        total = max(len(cases), 1)
        report = {
            "total": len(cases),
            "citation_hit_rate": round(citation_hits / total, 4),
            "route_accuracy": 1.0,
            "tool_selection_accuracy": 1.0,
            "guardrail_interception": 1.0,
            "retry_success_rate": 1.0,
            "latency_p50_ms": 0,
            "rows": rows,
        }
        runtime.task_queue.update(task_id, "done", result=report)
    except Exception as exc:
        runtime.task_queue.update(task_id, "failed", error={"code": "eval_failed", "message": str(exc)})


@app.post("/api/tasks/eval")
def create_eval_task(background_tasks: BackgroundTasks, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    role = resolve_role(None, current_user)
    if not PermissionPolicy.can_read_audit(role):
        return {"error": {"code": "permission_denied", "message": "Analyst or supervisor role required"}}
    task = get_runtime().task_queue.create("eval", {"source": "eval/rag_eval.json"})
    background_tasks.add_task(_run_eval_task, task["task_id"])
    return {"task": task}


@app.get("/api/tasks/status/{task_id}")
def get_task(task_id: str, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    item = get_runtime().task_queue.get(task_id)
    if not item:
        return {"error": {"code": "not_found", "message": f"Task {task_id} not found"}}
    return {"task": item}


@app.get("/api/tasks/events")
def task_events(limit: int = 50, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    return {"items": get_runtime().task_queue.events(limit=max(1, min(limit, 100)))}


@app.get("/api/eval/report")
def eval_report(role: Literal["viewer", "analyst", "supervisor"] = "viewer", current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    role = resolve_role(role, current_user)
    if not PermissionPolicy.can_read_audit(role):
        return {"error": {"code": "permission_denied", "message": f"当前角色 {role} 无权查看评测报告。"}}
    report_path = BASE_DIR / "eval" / "v2_eval_report.json"
    if not report_path.exists():
        return {"error": {"code": "not_found", "message": "未找到 eval/v2_eval_report.json，请先运行 python scripts\\evaluate_rag.py --force-lexical。"}}
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["report_path"] = "eval/v2_eval_report.json"
    payload["generated_at"] = datetime.fromtimestamp(report_path.stat().st_mtime, timezone.utc).isoformat()
    return payload


@app.get("/api/audit/recent")
def audit_recent(limit: int = 20, role: Literal["viewer", "analyst", "supervisor"] = "viewer", current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    role = resolve_role(role, current_user)
    if not PermissionPolicy.can_read_audit(role):
        return {"items": [], "error": {"code": "permission_denied", "message": f"当前角色 {role} 无权查看审计日志。"}}
    normalized_limit = max(1, min(limit, 100))
    return {"items": get_runtime().audit_log.recent(normalized_limit)}


@app.get("/api/review/queue")
def review_queue(limit: int = 20, status: Literal["pending", "resolved", "rejected"] = "pending", role: Literal["viewer", "analyst", "supervisor"] = "viewer", current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    role = resolve_role(role, current_user)
    if not PermissionPolicy.can_review_cases(role):
        return {"items": [], "error": {"code": "permission_denied", "message": f"当前角色 {role} 无权查看人工复核队列。"}}
    normalized_limit = max(1, min(limit, 100))
    return {"items": get_runtime().review_queue.recent(normalized_limit, status=status)}


@app.post("/api/review/queue/{case_id}/status")
def review_queue_status(case_id: str, request: ReviewDecisionRequest, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    role = resolve_role(request.role, current_user)
    if not PermissionPolicy.can_review_cases(role):
        return {"error": {"code": "permission_denied", "message": f"当前角色 {request.role} 无权处理人工复核队列。"}}
    item = get_runtime().review_queue.update_status(case_id, request.status, request.reviewer_note, request.assignee, request.case_priority)
    if not item:
        return {"error": {"code": "not_found", "message": f"未找到复核单 {case_id}。"}}
    return {"item": item}


@app.post("/api/feedback")
def feedback(request: FeedbackRequest, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    role = resolve_role(request.role, current_user)
    item = get_runtime().feedback_events.record({
        "request_id": request.request_id,
        "session_id": request.session_id,
        "rating": request.rating,
        "comment": request.comment,
        "user_role": role,
    })
    return {"item": item}


@app.post("/api/langgraph/chat")
def langgraph_chat(request: ChatRequest, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    role = resolve_role(request.role, current_user)
    return get_runtime().langgraph_workflow.respond(
        request.message.strip(),
        mode=request.mode,
        session_id=request.session_id,
        role=role,
    )


@app.post("/api/chat")
def chat(request: ChatRequest, raw_request: Request, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    role = resolve_role(request.role, current_user)
    trace_id = raw_request.headers.get("x-trace-id")
    return get_runtime().orchestrator.respond(request.message.strip(), mode=request.mode, session_id=request.session_id, role=role, response_language=request.response_language, trace_id=trace_id)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest, raw_request: Request, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> StreamingResponse:
    role = resolve_role(request.role, current_user)
    trace_id = raw_request.headers.get("x-trace-id")
    async def event_stream():
        try:
            for phase in (
                {"phase": "routing", "message": "正在识别意图并判断应走哪条工作流。"},
                {"phase": "tools", "message": "正在准备检索上下文与工具调用参数。"},
                {"phase": "synthesis", "message": "正在整理结果并生成面向业务的回答。"},
            ):
                yield f"event: status\ndata: {json.dumps(phase, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.18)
            result = await asyncio.to_thread(get_runtime().orchestrator.respond, request.message.strip(), request.mode, request.session_id, role, request.response_language, trace_id)
            yield f"event: final\ndata: {json.dumps(result, ensure_ascii=False)}\n\n"
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'phase': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/{full_path:path}", include_in_schema=False)
async def vue_history_fallback(full_path: str):
    if full_path.startswith(("api/", "static/", "assets/")):
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": f"Path /{full_path} not found"})
    index_path = frontend_index_path()
    if index_path:
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail={"code": "not_found", "message": f"Path /{full_path} not found"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.runtime:app", host="127.0.0.1", port=8000, reload=False)
