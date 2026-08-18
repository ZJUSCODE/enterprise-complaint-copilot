from __future__ import annotations

import json
import time
import uuid
from typing import Any

from app.audit_stores import AuditLogStore, HumanReviewQueue
from app.analytics import LocalAnalyticsEngine
from app.config import Settings, logger
from app.domain import contains_any, detect_category_from_query
from app.function_agent import FunctionCallingAgent
from app.permissions import PermissionPolicy
from app.rag import LangChainRAGService, PolicyKnowledgeBase
from app.routing import AutoRouter
from app.stores import RedisRuntime, SessionMemoryStore
from app.ticket_store import QueryFilters, ReadOnlySQLiteStore
from app.utils import (
    add_token_usage,
    estimate_cost,
    estimate_cost_breakdown,
    summarize_text,
    timed_call,
)


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
            "model_call_count": len(response.get("model_trace", []) or []),
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
        query_plan = self.function_agent.plan_refund_query(message)
        if query_plan.get("unsupported_reason"):
            return {
                "mode": "sql_rag_chain",
                "title": "查询能力边界",
                "summary": f"无法按原问题执行：{query_plan['unsupported_reason']} 请改问具体类目、客诉类型或赔付金额阈值。",
                "session_id": sid,
                "highlights": ["未生成近似 SQL，也未丢弃原问题中的分组条件。"],
                "tool_trace": [],
                "error": {"code": "unsupported_query_shape", "message": query_plan["unsupported_reason"]},
                "_token_usage": query_plan.get("token_usage", {}),
                "degradation_path": "unsupported_query_shape",
            }
        sql_args = query_plan["arguments"]
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
        total_token_usage = add_token_usage(query_plan.get("token_usage", {}), rag_token_usage)
        rag_cost_breakdown = estimate_cost_breakdown(self.settings, total_token_usage)
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
            rag_answer,
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
            "_token_usage": total_token_usage,
            "_cost_breakdown": rag_cost_breakdown,
            "model_trace": [*query_plan.get("model_trace", []), *rag_result.get("model_trace", [])],
            "degradation_path": query_plan.get("fallback_reason") or rag_result.get("fallback_reason"),
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
                "model_trace": result.get("model_trace", []),
                "_token_usage": result.get("token_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
                "_cost_breakdown": result.get("cost_breakdown"),
            }
        if mode == "sql_rag_chain":
            return self._respond_sql_rag_chain(message, session_id=session_id)
        if mode in {"router_demo", "auto"}:
            decision = self.router.route(message)
            delegated = self._respond_impl(message, decision["mode"], session_id=session_id)
            delegated["_token_usage"] = add_token_usage(delegated.get("_token_usage", {}), decision.get("_token_usage", {}))
            delegated["model_trace"] = [*decision.get("model_trace", []), *delegated.get("model_trace", [])]
            delegated["mode"] = mode
            delegated["title"] = "Router Demo" if mode == "router_demo" else delegated.get("title", "Auto Router")
            delegated.setdefault("highlights", [])
            delegated["highlights"] = [f"路由结果：{decision['mode']}", f"路由来源：{decision['source']}", f"路由置信度：{decision['confidence']:.2f}", f"路由原因：{decision['reason']}", *delegated["highlights"]]
            delegated["route"] = {key: value for key, value in decision.items() if not key.startswith("_") and key != "model_trace"}
            return delegated
        return self.function_agent.respond(message, session_id=session_id)
