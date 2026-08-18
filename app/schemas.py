from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class GetUserRiskArgs(BaseModel):
    user_id: str = Field(min_length=6)


class QueryRefundArgs(BaseModel):
    query: str = Field(min_length=2)
    category: str | None = None
    complaint_type: str | None = None
    amount_threshold: float | None = Field(default=None, ge=0)


class SearchPolicyArgs(BaseModel):
    query: str = Field(min_length=2)
    category: str | None = None


class QueryOrderStatusArgs(BaseModel):
    order_id: str = Field(min_length=8)


class QueryLogisticsStatusArgs(BaseModel):
    order_id: str = Field(min_length=8)


class QueryRefundEligibilityArgs(BaseModel):
    order_id: str = Field(min_length=8)
    reason: str | None = Field(default=None, max_length=300)


class QueryPolicyByMarketArgs(BaseModel):
    market: str = Field(min_length=2, max_length=12)
    topic: str = Field(min_length=2, max_length=120)


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=6, max_length=128)


class AuthUser(BaseModel):
    id: str
    username: str
    display_name: str
    role: Literal["viewer", "analyst", "supervisor"]


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str
    user: AuthUser


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    mode: Literal["function_call_agent", "sql_rag_chain", "langchain_rag", "router_demo", "auto", "modular_rag"] = "function_call_agent"
    session_id: str | None = None
    role: Literal["viewer", "analyst", "supervisor"] | None = "analyst"
    response_language: Literal["auto", "zh", "en"] = "auto"


class ReviewDecisionRequest(BaseModel):
    status: Literal["pending", "resolved", "rejected"] = "resolved"
    reviewer_note: str | None = Field(default=None, max_length=500)
    role: Literal["viewer", "analyst", "supervisor"] | None = "viewer"
    assignee: str | None = Field(default=None, max_length=80)
    case_priority: Literal["low", "medium", "high", "critical"] | None = None


class FeedbackRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=80)
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=500)
    session_id: str | None = Field(default=None, max_length=80)
    role: Literal["viewer", "analyst", "supervisor"] | None = "analyst"


class ToolInvocationRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)
    role: Literal["viewer", "analyst", "supervisor"] | None = "analyst"


class MCPRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str = Field(min_length=1, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)
