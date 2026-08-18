from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import (
    APP_TITLE,
    AUDIT_DB_PATH,
    BASE_DIR,
    FRONTEND_ASSETS_DIR,
    FRONTEND_DIST_DIR,
    KB_DIR,
    logger,
)
from app.domain import COMPLAINT_PATTERNS, POLICY_PATTERNS, contains_any
from app.permissions import PermissionPolicy
from app.http_auth import _bearer_token, optional_current_user, require_current_user, resolve_role
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
from app.runtime_state import RuntimeState, get_runtime, initialize_runtime
from app.ticket_store import (
    MySQLReadOnlyTicketStore,
    QueryFilters,
    ReadOnlySQLiteStore,
    build_tickets_export_frame,
)
from app.utils import (
    SQL_FORBIDDEN_KEYWORDS,
    lexical_overlap_score,
    safe_json_loads,
    summarize_text,
    timed_call,
    validate_readonly_sql,
)


def __getattr__(name: str) -> Any:
    if name in {"settings", "redis_runtime", "user_store", "task_queue", "analytics", "sql_store", "knowledge_base", "audit_log", "review_queue", "feedback_events", "orchestrator", "tool_registry", "langgraph_workflow"}:
        return getattr(get_runtime(), name)
    raise AttributeError(name)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_runtime()
    yield


app = FastAPI(title=APP_TITLE, lifespan=lifespan)
if FRONTEND_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="frontend-assets")


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
    index_path = frontend_index_path()
    if index_path:
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Frontend not built. Run: cd frontend && npm run build"})


@app.get("/review")
async def review_center():
    index_path = frontend_index_path()
    if index_path:
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Frontend not built. Run: cd frontend && npm run build"})


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
        eval_path = BASE_DIR / "eval" / "agent_eval_cases.json"
        cases = json.loads(eval_path.read_text(encoding="utf-8"))
        router = runtime.orchestrator.router
        function_agent = runtime.orchestrator.function_agent
        latencies: list[float] = []

        # 1. Route accuracy
        route_cases = cases.get("route", [])
        route_hits = 0
        route_rows = []
        for case in route_cases:
            start = time.perf_counter()
            decision = router.route(case["question"])
            latencies.append((time.perf_counter() - start) * 1000)
            match = decision.get("mode") == case.get("expected_mode")
            route_hits += int(match)
            route_rows.append({"question": case["question"], "expected": case.get("expected_mode"), "actual": decision.get("mode"), "match": match})
        route_total = max(len(route_cases), 1)

        # 2. Tool selection accuracy (using no-LLM fallback for determinism)
        tool_cases = cases.get("tool", [])
        tool_hits = 0
        tool_rows = []
        original_client = function_agent.client
        function_agent.client = None  # force deterministic fallback
        for case in tool_cases:
            start = time.perf_counter()
            result = function_agent.respond(case["question"])
            latencies.append((time.perf_counter() - start) * 1000)
            trace = result.get("tool_trace", [])
            actual_tool = trace[0].get("tool") if trace else None
            match = actual_tool == case.get("expected_tool")
            tool_hits += int(match)
            tool_rows.append({"question": case["question"], "expected": case.get("expected_tool"), "actual": actual_tool, "match": match})
        function_agent.client = original_client
        tool_total = max(len(tool_cases), 1)

        # 3. Guardrail interception
        guardrail_cases = cases.get("guardrail", [])
        guardrail_hits = 0
        guardrail_rows = []
        for case in guardrail_cases:
            start = time.perf_counter()
            result = function_agent._guardrail(case["question"])
            latencies.append((time.perf_counter() - start) * 1000)
            blocked = result is not None and result.get("mode") == "guardrail"
            guardrail_hits += int(blocked)
            guardrail_rows.append({"question": case["question"], "tag": case.get("tag"), "blocked": blocked})
        guardrail_total = max(len(guardrail_cases), 1)

        # 4. RAG citation (if available)
        rag_cases_path = BASE_DIR / "eval" / "rag_eval.json"
        citation_hits = 0
        citation_rows = []
        if rag_cases_path.exists():
            rag_cases = json.loads(rag_cases_path.read_text(encoding="utf-8"))
            for case in rag_cases:
                start = time.perf_counter()
                result = runtime.orchestrator.langchain_rag.query(case["question"], top_k=3)
                latencies.append((time.perf_counter() - start) * 1000)
                ids = [source.get("id") for source in result.get("sources", [])]
                hit = case["expected_doc_id"] in ids
                citation_hits += int(hit)
                citation_rows.append({"question": case["question"], "expected_doc_id": case["expected_doc_id"], "returned_doc_ids": ids, "citation_hit": hit})
            citation_total = max(len(rag_cases), 1)
        else:
            citation_total = 1

        latency_ms = round(sorted(latencies)[len(latencies) // 2], 2) if latencies else 0

        report = {
            "route_cases": len(route_cases),
            "route_accuracy": round(route_hits / route_total, 4),
            "tool_cases": len(tool_cases),
            "tool_selection_accuracy": round(tool_hits / tool_total, 4),
            "guardrail_cases": len(guardrail_cases),
            "guardrail_interception": round(guardrail_hits / guardrail_total, 4),
            "citation_cases": len(citation_rows),
            "citation_hit_rate": round(citation_hits / citation_total, 4),
            "latency_p50_ms": latency_ms,
            "total_cases": len(route_cases) + len(tool_cases) + len(guardrail_cases) + len(citation_rows),
            "route_rows": route_rows,
            "tool_rows": tool_rows,
            "guardrail_rows": guardrail_rows,
            "citation_rows": citation_rows,
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


@app.get("/api/feedback/export")
def feedback_export(limit: int = 100, role: Literal["viewer", "analyst", "supervisor"] = "viewer", current_user: dict[str, Any] | None = Depends(optional_current_user)) -> StreamingResponse:
    resolved_role = resolve_role(role, current_user)
    if not PermissionPolicy.can_read_audit(resolved_role):
        return JSONResponse(status_code=403, content={"error": {"code": "permission_denied", "message": f"当前角色 {resolved_role} 无权导出 SFT 数据。"}})
    runtime = get_runtime()
    normalized_limit = max(1, min(limit, 1000))
    feedback_items = runtime.feedback_events.recent(normalized_limit)
    audit_items = runtime.audit_log.recent(normalized_limit)
    audit_map = {item["request_id"]: item for item in audit_items}
    lines = []
    for fb in feedback_items:
        audit = audit_map.get(fb["request_id"], {})
        user_message = audit.get("user_message", "")
        response_title = audit.get("response_title", "")
        sft_row = {
            "messages": [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": response_title},
            ],
            "rating": fb["rating"],
            "comment": fb.get("comment"),
            "request_id": fb["request_id"],
            "session_id": fb.get("session_id"),
            "user_role": fb.get("user_role", "analyst"),
            "created_at": fb.get("created_at"),
        }
        lines.append(json.dumps(sft_row, ensure_ascii=False))
    body = "\n".join(lines) + "\n" if lines else ""
    return StreamingResponse(
        iter([body]),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="sft_feedback_export.jsonl"'},
    )


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
    import queue, threading

    def run_stream(q: queue.Queue):
        try:
            for event in get_runtime().orchestrator.respond_stream(
                request.message.strip(), request.mode, request.session_id, role, request.response_language, trace_id,
            ):
                q.put(event)
        except Exception as exc:
            q.put({"type": "error", "message": str(exc)})
        finally:
            q.put(None)

    async def event_stream():
        q: queue.Queue = queue.Queue()
        thread = threading.Thread(target=run_stream, args=(q,), daemon=True)
        thread.start()
        while True:
            event = await asyncio.to_thread(q.get)
            if event is None:
                break
            etype = event.pop("type", "status")
            sse_event = "token" if etype == "token" else etype
            payload = event.get("data") if etype == "final" else event
            yield f"event: {sse_event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ── Document Management API ──────────────────────────────────────────────

@app.get("/api/documents")
def list_documents(current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    """List all documents in the knowledge base."""
    runtime = get_runtime()
    documents = []
    if KB_DIR.exists():
        for f in sorted(KB_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() in runtime.doc_parser.supported_extensions() | {".md", ".json"}:
                stat = f.stat()
                documents.append({
                    "filename": f.name,
                    "size_bytes": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "extension": f.suffix.lower(),
                })
    return {"items": documents, "total": len(documents)}


@app.post("/api/documents")
async def upload_document(file: UploadFile, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    """Upload and process a new document."""
    runtime = get_runtime()
    try:
        filename = file.filename
        if not filename:
            return {"error": {"code": "missing_filename", "message": "Filename is required"}}
        content = await file.read()

        # Save to knowledge_base/
        KB_DIR.mkdir(parents=True, exist_ok=True)
        dest = KB_DIR / filename
        dest.write_bytes(content)

        # Parse and process
        sections = runtime.doc_parser.parse(str(dest))
        cleaned = runtime.doc_cleaner.clean(sections)
        chunks = runtime.chunking_engine.chunk(cleaned, source_file=filename, source_type=dest.suffix.lower())

        # Record lineage
        for chunk in chunks:
            runtime.lineage_tracker.record(
                chunk_id=chunk.metadata.chunk_id,
                source_file=filename,
                source_page=chunk.metadata.page_number,
                source_section=chunk.metadata.section_title,
            )

        # Embed and write to ChromaDB
        rag = runtime.orchestrator.langchain_rag
        embedded_count = 0
        if rag.available and rag.collection and rag.embeddings:
            try:
                name_lower = filename.lower()
                category = "售后" if "after_sales" in name_lower else "物流" if "logistics" in name_lower else "生鲜" if "fresh" in name_lower else "通用"
                texts = [c.text for c in chunks]
                ids = [c.metadata.chunk_id for c in chunks]
                metadatas = [{
                    "doc_id": c.metadata.chunk_id,
                    "title": c.metadata.section_title or Path(filename).stem,
                    "category": category,
                    "citation": f"{filename} > {c.metadata.section_title}" if c.metadata.section_title else filename,
                    "source_file": filename,
                    "section_title": c.metadata.section_title,
                    "is_parent": False,
                } for c in chunks]
                vectors = rag.embeddings.embed_documents(texts)
                rag.collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=vectors)
                embedded_count = len(chunks)
            except Exception as exc:
                logger.warning("Failed to embed chunks to ChromaDB: %s", exc)

        # Audit
        actor = (current_user or {}).get("username", "system")
        runtime.doc_audit.log("document", "upload", actor=actor, target=filename, details={
            "chunks_created": len(chunks),
            "embedded_to_vectordb": embedded_count,
            "file_size": len(content),
        })

        return {
            "filename": filename,
            "sections_parsed": len(sections),
            "sections_after_cleaning": len(cleaned),
            "chunks_created": len(chunks),
            "embedded_to_vectordb": embedded_count,
        }
    except Exception as exc:
        return {"error": {"code": "upload_failed", "message": str(exc)}}


@app.delete("/api/documents/{filename}")
def delete_document(filename: str, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    """Remove a document from the knowledge base and its chunks from ChromaDB."""
    runtime = get_runtime()
    file_path = KB_DIR / filename
    if not file_path.exists():
        return {"error": {"code": "not_found", "message": f"Document {filename} not found"}}
    file_path.unlink()

    # Remove from ChromaDB
    rag = runtime.orchestrator.langchain_rag
    removed_from_vectordb = 0
    if rag.available and rag.collection:
        try:
            results = rag.collection.get(where={"source_file": filename})
            if results and results.get("ids"):
                rag.collection.delete(ids=results["ids"])
                removed_from_vectordb = len(results["ids"])
        except Exception as exc:
            logger.warning("Failed to remove chunks from ChromaDB: %s", exc)

    actor = (current_user or {}).get("username", "system")
    runtime.doc_audit.log("document", "delete", actor=actor, target=filename, details={
        "removed_from_vectordb": removed_from_vectordb,
    })
    return {"deleted": filename, "removed_from_vectordb": removed_from_vectordb}


@app.get("/api/documents/{filename}/lineage")
def document_lineage(filename: str, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    """Get chunk lineage for a document."""
    runtime = get_runtime()
    chunk_ids = runtime.lineage_tracker.get_chunks_from_file(filename)
    lineages = []
    for cid in chunk_ids:
        lineage = runtime.lineage_tracker.get_lineage(cid)
        if lineage:
            lineages.append({
                "chunk_id": lineage.chunk_id,
                "source_file": lineage.source_file,
                "source_page": lineage.source_page,
                "source_section": lineage.source_section,
                "processing_steps": [{"step_name": s.step_name, "timestamp": s.timestamp, "duration_ms": s.duration_ms} for s in lineage.processing_steps],
                "created_at": lineage.created_at,
            })
    return {"filename": filename, "chunks": len(lineages), "lineages": lineages}


@app.get("/api/versions")
def list_versions(branch: str | None = None, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    """List KB versions."""
    runtime = get_runtime()
    versions = runtime.version_manager.list_versions(branch=branch)
    return {"items": [
        {
            "version_id": v.version_id,
            "branch": v.branch,
            "parent_id": v.parent_id,
            "timestamp": v.timestamp,
            "message": v.message,
            "author": v.author,
            "chunk_count": v.chunk_count,
            "added": v.added,
            "removed": v.removed,
            "modified": v.modified,
        }
        for v in versions
    ]}


@app.post("/api/versions")
def create_version(request: Request, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    """Create a new KB version snapshot."""
    runtime = get_runtime()
    # Collect current chunks from lineage
    chunks = []
    if KB_DIR.exists():
        for f in KB_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in runtime.doc_parser.supported_extensions() | {".md"}:
                try:
                    sections = runtime.doc_parser.parse(str(f))
                    file_chunks = runtime.chunking_engine.chunk(sections, source_file=f.name, source_type=f.suffix.lower())
                    for c in file_chunks:
                        chunks.append({"id": c.metadata.chunk_id, "text": c.text, "source": f.name})
                except Exception:
                    pass

    actor = (current_user or {}).get("username", "system")
    record = runtime.version_manager.create_version(
        branch="main",
        message=f"Snapshot with {len(chunks)} chunks",
        author=actor,
        chunks=chunks,
    )
    runtime.doc_audit.log("document", "version_create", actor=actor, details={"version_id": record.version_id, "chunk_count": len(chunks)})
    return {"version": {"version_id": record.version_id, "chunk_count": record.chunk_count, "timestamp": record.timestamp}}


@app.post("/api/versions/{version_id}/rollback")
def rollback_version(version_id: str, current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    """Rollback to a specific version."""
    runtime = get_runtime()
    actor = (current_user or {}).get("username", "system")
    chunks = runtime.version_manager.rollback(version_id, author=actor)
    if chunks is None:
        return {"error": {"code": "not_found", "message": f"Version {version_id} not found"}}
    runtime.doc_audit.log("document", "version_rollback", actor=actor, target=version_id, details={"chunks_restored": len(chunks)})
    return {"restored": version_id, "chunks": len(chunks)}


@app.get("/api/document-audit")
def document_audit_log(
    category: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    limit: int = 50,
    current_user: dict[str, Any] | None = Depends(optional_current_user),
) -> dict[str, Any]:
    """Query document audit log."""
    runtime = get_runtime()
    events = runtime.doc_audit.query(category=category, action=action, actor=actor, limit=min(limit, 100))
    return {"items": [
        {
            "event_id": e.event_id,
            "timestamp": e.timestamp,
            "category": e.category,
            "action": e.action,
            "actor": e.actor,
            "target": e.target,
            "details": e.details,
            "result": e.result,
        }
        for e in events
    ]}


@app.get("/api/document-audit/stats")
def document_audit_stats(current_user: dict[str, Any] | None = Depends(optional_current_user)) -> dict[str, Any]:
    """Get document audit statistics."""
    return get_runtime().doc_audit.stats()


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
