# Architecture Overview

This project is an enterprise-style AI Agent workbench for complaint risk triage. It is designed to show how an LLM can be placed inside a controlled business workflow instead of being exposed as a generic chatbot.

## System Shape

```text
Vue3 Workbench
  -> FastAPI runtime
    -> JWT / RBAC
    -> Guardrail
    -> AutoRouter
      -> FunctionCallingAgent
      -> SQL + RAG chain
      -> LangChain RAG
    -> ToolRegistry / MCP
    -> Human review queue
    -> Audit log
```

The backend is intentionally split by responsibility:

| Module | Responsibility |
| --- | --- |
| `app/runtime.py` | FastAPI app wiring, runtime initialization, HTTP routes |
| `app/orchestrator.py` | Request-level orchestration, audit, review queue, token/cost metadata |
| `app/function_agent.py` | Function calling loop, deterministic fallback, tool argument validation |
| `app/tool_registry.py` | Tool catalog, RBAC checks, MCP-compatible list/call surface |
| `app/langgraph_workflow.py` | LangGraph node workflow for permission, guardrail, routing, execution, review, audit |
| `app/routing.py` | Rule-first and optional LLM-based router |
| `app/rag.py` | Policy knowledge base and LangChain RAG service |
| `app/ticket_store.py` | Read-only SQLite/MySQL ticket query layer |
| `app/audit_stores.py` | Audit log, review queue, feedback events |
| `app/analytics.py` | Local data analysis and deterministic risk reports |
| `app/domain.py` | Domain rules, categories, query intent patterns, guardrail patterns |
| `app/schemas.py` | Pydantic request and tool argument schemas |

## Agent Execution Flow

1. The user submits a natural-language task from the Vue workbench.
2. FastAPI resolves authentication and role.
3. The orchestrator checks role-level access for the requested mode.
4. Guardrail blocks write actions, prompt injection, unsafe SQL intent, and bulk data export.
5. The router chooses `function_call_agent`, `langchain_rag`, or `sql_rag_chain`.
6. The selected path invokes only registered read-only tools.
7. Tool results are returned with `tool_trace`, SQL preview, citations, timing, token usage, and estimated cost.
8. High-risk or uncertain cases enter `HumanReviewQueue`.
9. Every request is recorded in the audit log with `request_id` and `trace_id`.

## Agent Modes

| Mode | Purpose | Interview talking point |
| --- | --- | --- |
| `function_call_agent` | Tool-calling workflow for user risk, order status, logistics, refund eligibility, and policy lookup | Shows OpenAI-style function calling with validation and fallback |
| `langchain_rag` | SOP/policy question answering with citations | Shows retrieval, fallback, and citation discipline |
| `sql_rag_chain` | Read-only data query followed by SOP reasoning | Shows how structured data and policy evidence can be combined |
| `router_demo` / `auto` | Automatic route selection | Shows routing policy and graceful degradation |
| `langgraph_chat` | Explicit workflow graph | Shows Agent workflow nodes and traceable transitions |

## Safety Model

The project demonstrates a layered safety model:

| Layer | Control |
| --- | --- |
| Authentication | JWT-based login |
| Authorization | `viewer`, `analyst`, `supervisor` roles |
| Mode permission | Role checks before Agent execution |
| Tool registry | Each tool has a required permission |
| SQL safety | Parameterized queries and read-only SQL validation |
| Guardrail | Blocks write operations, prompt injection, unsafe SQL, and bulk export |
| Human review | Escalates high-risk or uncertain cases |
| Audit | Records route, tool trace, SQL preview, latency, token/cost metadata |

This is the most important design point: the Agent can recommend, query, retrieve, and escalate, but it never directly refunds, modifies orders, deletes records, or exports sensitive data.

## RAG Design

The RAG path is built around support policy documents:

1. Load policy records from `knowledge_base/policies.json`.
2. Prefer vector search when LangChain dependencies and a vector store are available.
3. Fall back to lexical search when external dependencies or API keys are missing.
4. Return citations and retrieval metadata to the UI.
5. Log the RAG call in `tool_trace` with timing and cost fields.

This makes the demo reliable offline while still showing the production path.

## Tool Registry and MCP

Tools are exposed through:

```text
GET  /api/tools/registry
POST /api/tools/invoke
POST /api/mcp
python scripts/mcp_stdio_server.py --role analyst
```

The same registry powers the UI, direct API calls, and MCP-style tool discovery. This is useful in interviews because it shows that the project treats tools as a governed platform surface rather than ad hoc helper functions.

## Observability

Each response includes operational metadata:

| Field | Purpose |
| --- | --- |
| `request_id` | Debug and audit correlation |
| `trace_id` | End-to-end trace correlation |
| `tool_trace` | Tool calls, arguments, timing, summaries |
| `sql_preview` | Explainable read-only query preview |
| `citations` | RAG evidence |
| `latency_ms` | Runtime performance |
| `token_usage` | LLM usage |
| `estimated_cost_usd` | Cost visibility |
| `retry_count` | Reliability signal |

## Evaluation and Demo Readiness

The project includes both code tests and product-level checks:

```powershell
python -m pytest tests
python scripts\demo_check.py
cd frontend
npm run build
```

Current verified baseline:

```text
pytest: 48 passed
demo_check: passed
frontend build: passed
```

## What This Shows for AI Agent Roles

This project is meant to demonstrate:

- Agent tool calling with typed arguments and deterministic fallback.
- RAG with citations and offline-safe fallback.
- Read-only SQL over business data.
- RBAC, guardrails, and human-in-the-loop review.
- MCP-style tool discovery and invocation.
- LangGraph workflow modeling.
- Auditability, cost tracking, and traceability.
- A production-shaped frontend rather than a notebook-only prototype.

## Production Gaps

The current project is a strong job-seeking prototype, not a full enterprise deployment. The next production steps would be:

1. Add SSO and tenant-aware data scopes.
2. Add field-level masking for sensitive IDs and user data.
3. Move audit logs to a durable service with retention policies.
4. Add async job queues for long-running RAG/evaluation tasks.
5. Add HTTP MCP gateway authentication and tool versioning.
6. Add load tests and service-level metrics.
7. Add deployment-specific secret management.
