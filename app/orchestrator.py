from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import re
import time
import uuid
from typing import Any, Generator

from app.audit_stores import AuditLogStore, HumanReviewQueue
from app.analytics import LocalAnalyticsEngine
from app.config import Settings, logger, KB_DIR
from app.domain import POLICY_PATTERNS, contains_any, detect_category_from_query
from app.function_agent import FunctionCallingAgent
from app.multi_agent import SupervisorAgent
from app.permissions import PermissionPolicy
from app.query_planner import QueryPlanner
from app.query_rewrite import QueryRewriter
from app.rag import LangChainRAGService, PolicyKnowledgeBase
from app.reflection import ReflectionEngine
from app.routing import AutoRouter
from app.stores import RedisRuntime, SessionMemoryStore
from app.ticket_store import QueryFilters, ReadOnlySQLiteStore
from app.utils import (
    estimate_cost,
    estimate_cost_breakdown,
    find_citation_answer_mapping,
    summarize_text,
    timed_call,
)
from app.pipeline import ModularRAGPipeline
from app.agentic_controller import AgenticRAGController
from app.modules.query_rewrite_module import QueryRewriteModule
from app.modules.query_planner_module import QueryPlannerModule
from app.modules.retriever_module import HybridRetrieverModule
from app.modules.generator_module import GeneratorModule
from app.modules.adaptive_router import AdaptiveRouterModule
from app.modules.knowledge_graph import KnowledgeGraphRetriever
from app.modules.reranker import CrossEncoderReranker
from app.modules.crag import CRAGCorrector
from app.modules.self_rag import SelfRAGCritic


@dataclass(frozen=True)
class ResponseContext:
    request_id: str
    trace_id: str
    started_at: float
    message: str
    mode: str
    session_id: str | None
    role: str
    response_language: str


@dataclass(frozen=True)
class StreamContext:
    started_at: float
    message: str
    mode: str
    session_id: str | None
    role: str
    response_language: str
    trace_id: str | None


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
        self.langchain_rag = LangChainRAGService(settings, knowledge_base)
        self.function_agent = FunctionCallingAgent(settings, analytics, sql_store, knowledge_base, self.memory, langchain_rag=self.langchain_rag)
        self.router = AutoRouter(settings)
        self.query_rewriter = QueryRewriter(
            llm_client=self.function_agent.client,
            model=settings.llm_model,
        )
        self.reflection_engine = ReflectionEngine()
        self.query_planner = QueryPlanner(
            llm_client=self.function_agent.client,
            model=settings.llm_model,
        )
        self.supervisor = SupervisorAgent(self)

        # Modular RAG Pipeline
        self.modular_pipeline = ModularRAGPipeline(modules=[
            QueryRewriteModule(self.query_rewriter),
            QueryPlannerModule(self.query_planner),
            AdaptiveRouterModule(),
            HybridRetrieverModule(self.langchain_rag),
            KnowledgeGraphRetriever(kb_dir=KB_DIR),
            CrossEncoderReranker(),
            CRAGCorrector(),
            GeneratorModule(llm_client=self.function_agent.client, model=settings.llm_model),
            SelfRAGCritic(llm_client=self.function_agent.client, model=settings.llm_model),
        ])
        self.agentic_controller = AgenticRAGController(
            llm_client=self.function_agent.client,
            model=settings.llm_model,
        )

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

        return self._finalize_response(
            response,
            ResponseContext(
                request_id=request_id,
                trace_id=trace_id,
                started_at=start,
                message=message,
                mode=mode,
                session_id=session_id,
                role=role,
                response_language=response_language,
            ),
        )

    def _finalize_response(self, response: dict[str, Any], context: ResponseContext) -> dict[str, Any]:
        final_response, token_usage = self._with_runtime_metadata(response, context)
        actual_mode = final_response.get("mode", context.mode)
        if context.session_id and actual_mode not in {"permission_denied", "guardrail", "degraded_error"}:
            self.memory.set_meta(context.session_id, "last_mode", actual_mode)
        final_response = self._with_review_case(final_response, context)
        self._record_audit(final_response, context, token_usage)
        self._log_response(final_response, context)
        return final_response

    def _with_runtime_metadata(self, response: dict[str, Any], context: ResponseContext) -> tuple[dict[str, Any], dict[str, Any]]:
        final_response = dict(response)
        latency_ms = round((time.perf_counter() - context.started_at) * 1000, 2)
        token_usage = final_response.pop("_token_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        cost_breakdown = final_response.pop("_cost_breakdown", None) or estimate_cost_breakdown(self.settings, token_usage)
        retry_count = int(final_response.pop("_retry_count", 0) or 0)
        estimated_cost = float(cost_breakdown.get("total_cost_usd", estimate_cost(self.settings, token_usage)))
        final_response.update({
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "latency_ms": latency_ms,
            "token_usage": token_usage,
            "cost_breakdown": cost_breakdown,
            "estimated_cost_usd": estimated_cost,
            "retry_count": retry_count,
            "response_language": context.response_language,
        })
        final_response["trace"] = {
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "latency_ms": latency_ms,
            "tool_call_count": len(final_response.get("tool_trace", []) or []),
            "rag_retrieval_ms": max([float(item.get("duration_ms", 0) or 0) for item in final_response.get("tool_trace", []) or [] if "rag" in str(item.get("tool", "")).lower()] or [0]),
            "token_usage": token_usage,
            "cost_breakdown": cost_breakdown,
            "estimated_cost_usd": estimated_cost,
            "retry_count": retry_count,
        }
        return final_response, token_usage

    def _with_review_case(self, response: dict[str, Any], context: ResponseContext) -> dict[str, Any]:
        if not response.get("review_required"):
            return response
        review_case = self.review_queue.enqueue({
            "request_id": context.request_id,
            "session_id": response.get("session_id") or context.session_id,
            "user_role": context.role,
            "source_mode": response.get("mode", context.mode),
            "reason": response.get("review_reason", "需要人工复核"),
            "user_message": context.message,
            "response_summary": response.get("summary"),
            "tool_trace": response.get("tool_trace", []),
            "case_priority": self._review_priority(response),
            "escalation_reason": response.get("review_reason"),
            "assignee": "supervisor_queue",
        })
        return {**response, "review_case": review_case}

    def _review_priority(self, response: dict[str, Any]) -> str:
        reason = str(response.get("review_reason", "")).lower()
        if response.get("mode") == "guardrail" or "high priority" in reason:
            return "high"
        return "medium"

    def _with_route_metadata(self, response: dict[str, Any], route_decision: dict[str, Any] | None, resolved_mode: str) -> dict[str, Any]:
        if not route_decision:
            return dict(response)
        return {
            **response,
            "route": route_decision,
            "highlights": [
                f"路由结果：{resolved_mode}",
                f"路由来源：{route_decision.get('source', '')}",
                *response.get("highlights", []),
            ],
        }

    def _record_audit(self, response: dict[str, Any], context: ResponseContext, token_usage: dict[str, Any]) -> None:
        self.audit_log.record({
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "session_id": response.get("session_id") or context.session_id,
            "mode": response.get("mode", context.mode),
            "route": response.get("route"),
            "blocked_by_guardrail": response.get("mode") == "guardrail",
            "blocked_by_permission": response.get("mode") == "permission_denied",
            "user_role": context.role,
            "user_message": context.message,
            "response_title": response.get("title"),
            "tool_trace": response.get("tool_trace", []),
            "sql_preview": response.get("sql_preview"),
            "latency_ms": response["latency_ms"],
            "token_usage": token_usage,
            "estimated_cost_usd": response["estimated_cost_usd"],
            "retry_count": response["retry_count"],
        })

    def _log_response(self, response: dict[str, Any], context: ResponseContext) -> None:
        logger.info(json.dumps({
            "event": "copilot_request",
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "mode": response.get("mode", context.mode),
            "role": context.role,
            "latency_ms": response["latency_ms"],
            "retry_count": response["retry_count"],
            "cost_usd": response["estimated_cost_usd"],
            "error_code": (response.get("error") or {}).get("code"),
        }, ensure_ascii=False))

    def _respond_sql_rag_chain(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        sid = self.memory.get_or_create(session_id)
        history = self.memory.recent_messages(sid, limit=6)
        rewrite_result = self.query_rewriter.rewrite(message, history)
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
        rag_result, rag_duration_ms = timed_call(
            self.langchain_rag.query, policy_query,
            category=sql_args.get("category"), top_k=3,
            history=history, rewritten_query=rewrite_result.rewritten_query,
        )
        citations = [
            {
                "label": item["citation"],
                "text": item["excerpt"],
                "retrieval_score": item.get("retrieval_score"),
                "rerank_score": item.get("rerank_score"),
                "source": item.get("source"),
                "rrf_score": item.get("rrf_score"),
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
        citation_highlights = find_citation_answer_mapping(rag_answer, citations)
        reflection = self.reflection_engine.check(rag_answer, message, citations)
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
            "citation_highlights": citation_highlights,
            "tool_trace": tool_trace,
            "query_rewrite": {
                "original": rewrite_result.original_query,
                "rewritten": rewrite_result.rewritten_query,
                "method": rewrite_result.rewrite_method,
                "rewrite_ms": rewrite_result.rewrite_ms,
            },
            "retrieval_mode": rag_result.get("retrieval_mode", "unknown"),
            "online_rag_metrics": rag_result.get("online_metrics", {}),
            "reflection": {"passed": reflection.passed, "issues": reflection.issues, "retries": reflection.retries},
            "review_required": needs_review,
            "review_reason": "SQL 命中高赔付质量问题异常，但 SOP 未提供按金额统一复核的明确条款，需人工按类目与风险补判。",
            "_token_usage": rag_token_usage,
            "_cost_breakdown": rag_cost_breakdown,
        }

    def _execute_plan(self, message: str, plan: "QueryPlan", session_id: str | None = None) -> dict[str, Any]:
        from app.query_planner import QueryPlan  # avoid circular import at module level
        all_tool_trace: list[dict[str, Any]] = []
        all_highlights: list[str] = []
        all_citations: list[dict[str, Any]] = []
        step_results: list[dict[str, Any]] = []
        for step in plan.steps:
            sub_result = self.function_agent.respond(step.query, session_id=session_id)
            step_results.append({"step_id": step.step_id, "query": step.query, "expected_tool": step.expected_tool, "title": sub_result.get("title", "")})
            all_tool_trace.extend(sub_result.get("tool_trace", []))
            all_highlights.extend(sub_result.get("highlights", []))
            all_citations.extend(sub_result.get("citations", []))
        summary_parts = [f"子任务 {s['step_id']}：{s['query']}" for s in step_results]
        summary = "复杂查询已分解为多个子任务执行：\n" + "\n".join(summary_parts)
        return {
            "mode": "multi_step",
            "title": "多步骤查询规划",
            "summary": summary,
            "session_id": self.memory.get_or_create(session_id),
            "highlights": all_highlights[:6],
            "citations": all_citations,
            "tool_trace": all_tool_trace,
            "query_plan": {
                "steps": [{"step_id": s.step_id, "query": s.query, "expected_tool": s.expected_tool, "depends_on": s.depends_on} for s in plan.steps],
                "decomposition_method": plan.decomposition_method,
            },
        }

    def _respond_modular_rag(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        """Execute the Modular + Agentic RAG pipeline."""
        sid = self.memory.get_or_create(session_id)
        history = self.memory.recent_messages(sid, limit=6)

        # Let agentic controller decide which modules to activate
        active_modules = self.agentic_controller.decide_pipeline(message)

        # Configure pipeline modules based on controller decision
        for module in self.modular_pipeline.modules:
            module.enabled = module.name in active_modules

        # Run the pipeline with history in metadata
        ctx = asyncio.run(self.modular_pipeline.run(message, initial_metadata={"history": history, "category": detect_category_from_query(message)}))

        # Build citations from results
        results = ctx.corrected_results or ctx.reranked_results or ctx.fused_results or ctx.vector_results
        citations = [
            {
                "label": r.citation,
                "text": r.excerpt,
                "retrieval_score": r.retrieval_score,
                "rerank_score": r.rerank_score,
                "source": r.source,
            }
            for r in results
        ]

        # Build tool trace
        tool_trace = [
            {
                "tool": "modular_rag",
                "arguments": {"query": message, "active_modules": active_modules},
                "duration_ms": sum(ctx.metadata.get("module_timings", {}).values()),
                "result_summary": summarize_text(ctx.answer, limit=180),
                "token_usage": ctx.metadata.get("rag_token_usage", {}),
                "cost_breakdown": ctx.metadata.get("rag_cost_breakdown", {}),
                "timing": ctx.metadata.get("rag_timing", {}),
            }
        ]

        # Build highlights
        highlights = [
            f"模块化 RAG Pipeline: 激活 {len(ctx.metadata.get('activated_modules', []))} 个模块",
            f"检索策略: {ctx.retrieval_strategy}",
        ]
        if ctx.metadata.get("kg_retriever", {}).get("entities_found"):
            highlights.append(f"图谱实体: {', '.join(ctx.metadata['kg_retriever']['entities_found'][:3])}")
        if ctx.metadata.get("crag", {}).get("status"):
            highlights.append(f"CRAG 状态: {ctx.metadata['crag']['status']}")

        self.memory.append(sid, "user", message)
        self.memory.append(sid, "assistant", ctx.answer)

        reflection_data = None
        if ctx.reflection:
            reflection_data = {
                "passed": ctx.reflection.passed,
                "issues": ctx.reflection.issues,
                "retries": ctx.reflection.retries,
            }

        return {
            "mode": "modular_rag",
            "title": "Modular + Agentic RAG",
            "summary": ctx.answer,
            "session_id": sid,
            "highlights": highlights,
            "citations": citations,
            "citation_highlights": find_citation_answer_mapping(ctx.answer, citations),
            "tool_trace": tool_trace,
            "query_rewrite": ctx.metadata.get("query_rewrite"),
            "retrieval_mode": ctx.metadata.get("retrieval_mode", ctx.retrieval_strategy),
            "online_rag_metrics": ctx.metadata.get("online_metrics"),
            "reflection": reflection_data,
            "modular_rag_metrics": {
                "activated_modules": ctx.metadata.get("activated_modules", []),
                "skipped_modules": ctx.metadata.get("skipped_modules", []),
                "module_timings": ctx.metadata.get("module_timings", {}),
                "retrieval_strategy": ctx.retrieval_strategy,
                "kg_entities": ctx.metadata.get("kg_retriever", {}).get("entities_found", []),
                "kg_triples": ctx.metadata.get("kg_retriever", {}).get("triples_retrieved", 0),
                "crag_status": ctx.metadata.get("crag", {}).get("status"),
                "self_rag_passed": ctx.metadata.get("self_rag", {}).get("passed"),
            },
            "_token_usage": ctx.metadata.get("rag_token_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
            "_cost_breakdown": ctx.metadata.get("rag_cost_breakdown"),
        }

    def _respond_impl(self, message: str, mode: str, session_id: str | None = None) -> dict[str, Any]:
        blocked = self.function_agent._guardrail(message)
        if blocked:
            return blocked

        # Memory follow-up: if mode is auto and previous turn used RAG/policy, stay on RAG
        # unless the new message has strong data-query intent
        effective_mode = mode
        if mode in {"auto", "router_demo"} and session_id:
            last_mode = self.memory.get_meta(session_id, "last_mode")
            last_tool = self.memory.get_meta(session_id, "last_tool")
            was_rag_context = last_mode in {"langchain_rag", "sql_rag_chain"} or last_tool == "search_policy_docs"
            if was_rag_context:
                has_strong_data_intent = contains_any(message, ["查询", "查一下", "明细", "统计", "分析", "超过", "多少", "金额", "top", "最多", "用户"])
                has_explicit_tool = re.search(r"[0-9a-f]{24,}", message, re.IGNORECASE)
                if not has_strong_data_intent and not has_explicit_tool:
                    effective_mode = "langchain_rag"

        plan = self.query_planner.plan(message)
        if plan.is_complex and effective_mode not in {"langchain_rag", "sql_rag_chain"}:
            return self._execute_plan(message, plan, session_id)
        if effective_mode == "langchain_rag":
            sid = self.memory.get_or_create(session_id)
            history = self.memory.recent_messages(sid, limit=6)
            rewrite_result = self.query_rewriter.rewrite(message, history)
            result, rag_duration_ms = timed_call(
                self.langchain_rag.query, message,
                category=detect_category_from_query(message), top_k=3,
                history=history, rewritten_query=rewrite_result.rewritten_query,
            )
            query_rewrite_meta = {
                "original": rewrite_result.original_query,
                "rewritten": rewrite_result.rewritten_query,
                "method": rewrite_result.rewrite_method,
                "rewrite_ms": rewrite_result.rewrite_ms,
            }
            citations = [{"label": item["citation"], "text": item["excerpt"], "retrieval_score": item.get("retrieval_score"), "rerank_score": item.get("rerank_score"), "source": item.get("source"), "rrf_score": item.get("rrf_score")} for item in result.get("sources", [])]
            citation_highlights = find_citation_answer_mapping(result["answer"], citations)
            reflection = self.reflection_engine.check(result["answer"], message, citations)
            return {
                "mode": "langchain_rag",
                "title": "LangChain RAG",
                "summary": result["answer"],
                "session_id": sid,
                "highlights": ["面向售后 SOP 的检索增强问答。", "先检索文档，再由模型基于上下文回答。", "当前实现适合讲解完整的 RAG pipeline。"],
                "citations": citations,
                "citation_highlights": citation_highlights,
                "tool_trace": [{
                    "tool": "langchain_rag",
                    "arguments": {"query": message, "top_k": 3, "retrieval_mode": result.get("retrieval_mode", "unknown")},
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
                "query_rewrite": query_rewrite_meta,
                "retrieval_mode": result.get("retrieval_mode", "unknown"),
                "online_rag_metrics": result.get("online_metrics", {}),
                "reflection": {"passed": reflection.passed, "issues": reflection.issues, "retries": reflection.retries},
                "degradation_path": result.get("fallback_reason"),
                "_token_usage": result.get("token_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
                "_cost_breakdown": result.get("cost_breakdown"),
            }
        if effective_mode == "sql_rag_chain":
            return self._respond_sql_rag_chain(message, session_id=session_id)
        if effective_mode == "modular_rag":
            return self._respond_modular_rag(message, session_id=session_id)
        if effective_mode == "multi_agent":
            return self.supervisor.coordinate(message, session_id=session_id)
        if effective_mode in {"router_demo", "auto"}:
            decision = self.router.route(message)
            delegated = self._respond_impl(message, decision["mode"], session_id=session_id)
            delegated["mode"] = effective_mode
            delegated["title"] = "Router Demo" if effective_mode == "router_demo" else delegated.get("title", "Auto Router")
            delegated.setdefault("highlights", [])
            delegated["highlights"] = [f"路由结果：{decision['mode']}", f"路由来源：{decision['source']}", f"路由置信度：{decision['confidence']:.2f}", f"路由原因：{decision['reason']}", *delegated["highlights"]]
            delegated["route"] = decision
            return delegated
        return self.function_agent.respond(message, session_id=session_id)

    def _finalize_stream_response(self, response: dict[str, Any], context: StreamContext) -> dict[str, Any]:
        return self._finalize_response(
            response,
            ResponseContext(
                request_id=str(uuid.uuid4()),
                trace_id=context.trace_id or str(uuid.uuid4()),
                started_at=context.started_at,
                message=context.message,
                mode=context.mode,
                session_id=context.session_id,
                role=context.role,
                response_language=context.response_language,
            ),
        )

    def _stream_permission_denied(self, context: StreamContext) -> Generator[dict[str, Any], None, None]:
        response = {
            "mode": "permission_denied",
            "title": "权限不足",
            "summary": f"当前角色 {context.role} 无权使用 {context.mode} 工作流。",
            "highlights": ["权限系统已阻止本次调用"],
            "tool_trace": [],
        }
        yield {"type": "final", "data": self._finalize_stream_response(response, context)}

    def _stream_function_agent(
        self,
        context: StreamContext,
        route_decision: dict[str, Any] | None,
        resolved_mode: str,
    ) -> Generator[dict[str, Any], None, None]:
        yield {"type": "status", "phase": "tools", "message": "正在调用工具并生成回答。"}
        for event in self.function_agent.respond_stream(context.message, session_id=context.session_id):
            if event.get("type") != "final":
                yield event
                continue
            response = self._with_route_metadata(event["data"], route_decision, resolved_mode)
            yield {"type": "status", "phase": "synthesis", "message": "正在整理结果。"}
            yield {"type": "final", "data": self._finalize_stream_response(response, context)}

    def _stream_completed_response(self, context: StreamContext) -> Generator[dict[str, Any], None, None]:
        response = self.respond(
            context.message,
            context.mode,
            context.session_id,
            context.role,
            context.response_language,
            context.trace_id,
        )
        yield {"type": "status", "phase": "tools", "message": "正在准备检索上下文与工具调用参数。"}
        yield from self._summary_token_events(response.get("summary", ""))
        yield {"type": "status", "phase": "synthesis", "message": "正在整理结果并生成面向业务的回答。"}
        yield {"type": "final", "data": response}

    def _summary_token_events(self, summary: str) -> Generator[dict[str, Any], None, None]:
        if not summary:
            return
        sentences = re.split(r"(?<=[。！？\n])", summary)
        for sentence in sentences:
            if sentence.strip():
                yield {"type": "token", "content": sentence}

    def respond_stream(
        self,
        message: str,
        mode: str,
        session_id: str | None = None,
        role: str = "analyst",
        response_language: str = "auto",
        trace_id: str | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Yield status, token, and final events for SSE streaming."""
        context = StreamContext(
            started_at=time.perf_counter(),
            message=message,
            mode=mode,
            session_id=session_id,
            role=role,
            response_language=response_language,
            trace_id=trace_id,
        )
        yield {"type": "status", "phase": "routing", "message": "正在识别意图并判断应走哪条工作流。"}

        if not PermissionPolicy.can_use_mode(role, mode):
            yield from self._stream_permission_denied(context)
            return

        resolved_mode = mode
        route_decision = None
        if mode in {"auto", "router_demo"}:
            route_decision = self.router.route(message)
            resolved_mode = route_decision["mode"]
            yield {"type": "status", "phase": "routing", "message": f"路由决策：{resolved_mode}（{route_decision.get('reason', '')}）"}

        if resolved_mode == "function_call_agent":
            yield from self._stream_function_agent(context, route_decision, resolved_mode)
            return

        yield from self._stream_completed_response(context)
