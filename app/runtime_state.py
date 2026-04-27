from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.audit_stores import AuditLogStore, FeedbackEventStore, HumanReviewQueue
from app.analytics import LocalAnalyticsEngine
from app.config import (
    AUDIT_DB_PATH,
    AUTH_DB_PATH,
    BASE_DIR,
    DATA_DIR,
    KB_DIR,
    SQLITE_DB_PATH,
    Settings,
    load_dotenv_file,
)
from app.langgraph_workflow import LangGraphWorkflow
from app.orchestrator import Orchestrator
from app.rag import PolicyKnowledgeBase
from app.stores import RedisRuntime, TaskQueueStore, UserStore
from app.ticket_store import MySQLReadOnlyTicketStore, ReadOnlySQLiteStore
from app.tool_registry import ToolRegistry


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
