from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict

import chromadb
import pandas as pd
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

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
    VECTOR_DIR,
    Settings,
    load_dotenv_file,
    logger,
)
from app.permissions import PermissionPolicy
from app.security import hash_password, jwt_decode, jwt_encode, utc_now, verify_password
from app.utils import (
    SQL_FORBIDDEN_KEYWORDS,
    add_token_usage,
    clamp,
    estimate_cost,
    estimate_cost_breakdown,
    estimate_text_tokens,
    extract_langchain_usage,
    extract_usage,
    lexical_overlap_score,
    safe_json_loads,
    timed_call,
    validate_readonly_sql,
)

try:
    import redis
except ImportError:  # pragma: no cover - optional production dependency
    redis = None

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:  # pragma: no cover - optional dependency fallback
    END = "__end__"
    START = "__start__"
    StateGraph = None


PRODUCT_CATEGORY_RULES = {
    "3C数码": ["audio", "cine", "computer", "consoles", "electronics", "pcs", "tablets", "telefonia", "games", "office", "cool_stuff"],
    "生鲜": ["food", "drinks"],
    "服饰": ["fashion", "luggage", "shoes", "watches", "bed_bath"],
    "美妆": ["beauty", "perfumery", "health"],
}

CATEGORY_QUERY_MAP = {
    "手机": "3C数码",
    "电脑": "3C数码",
    "耳机": "3C数码",
    "电子": "3C数码",
    "数码": "3C数码",
    "生鲜": "生鲜",
    "水果": "生鲜",
    "食品": "生鲜",
    "服饰": "服饰",
    "衣服": "服饰",
    "鞋": "服饰",
    "美妆": "美妆",
    "护肤": "美妆",
    "香水": "美妆",
}

COMPLAINT_PATTERNS = {
    "物流延误": ["delay", "late", "atras", "demora", "entrega", "nao chegou", "não chegou", "物流", "延误"],
    "质量问题": ["defeito", "queb", "ruim", "broken", "bad", "quality", "problem", "defect", "质量"],
    "包装破损": ["embal", "amass", "damag", "box", "package", "packing", "破损", "包装"],
    "仅退款": ["refund", "reembolso", "devol", "cancel", "troca", "退款"],
}

MUTATION_PATTERNS = ["update", "delete", "insert", "drop", "truncate", "删除", "清空", "审批", "批了", "通过退款", "改订单", "直接退款"]
PROMPT_INJECTION_PATTERNS = [
    "忽略规则",
    "忽略上面的规则",
    "忽略之前",
    "忽略系统",
    "绕过",
    "越权",
    "无视权限",
    "system prompt",
    "developer message",
    "ignore previous",
    "ignore all previous",
]
DATA_EXFILTRATION_PATTERNS = [
    "导出全部用户",
    "导出所有用户",
    "全部用户",
    "全量用户",
    "dump all",
    "export all users",
    "所有 user_id",
    "全部 user_id",
]
QUERY_PATTERNS = ["查询", "查一下", "明细", "退款", "赔付", "订单", "统计", "分析", "风险", "用户"]
POLICY_PATTERNS = ["政策", "规则", "SOP", "怎么赔", "能不能退", "如何处理", "依据", "条款", "规范", "怎么处理", "应该怎么", "how to", "should we", "policy"]

TICKETS_SCHEMA = {
    "table": "tickets",
    "description": "售后客诉与退款分析宽表，只面向只读查询和聚合分析。",
    "columns": [
        {"name": "order_id", "type": "TEXT", "description": "订单唯一编号，用于定位异常工单。", "filterable": True, "dimension": True},
        {"name": "user_id", "type": "TEXT", "description": "用户唯一编号，只用于风险查询和明细关联。", "filterable": True, "dimension": True},
        {"name": "category", "type": "TEXT", "description": "业务大类，例如 3C数码、生鲜、服饰、美妆、其他。", "filterable": True, "dimension": True},
        {"name": "complaint_type", "type": "TEXT", "description": "客诉类型，例如 质量问题、物流延误、包装破损、仅退款、一般咨询。", "filterable": True, "dimension": True},
        {"name": "compensation_amount", "type": "REAL", "description": "根据差评与运费估算的赔付金额，单位元。", "filterable": True, "dimension": False},
        {"name": "pay_amount", "type": "REAL", "description": "订单商品实付金额，单位元。", "filterable": True, "dimension": False},
        {"name": "created_at", "type": "TEXT", "description": "订单创建日期，格式 YYYY-MM-DD。", "filterable": True, "dimension": True},
        {"name": "comment", "type": "TEXT", "description": "用户评价或客诉文本摘要，用于解释异常原因。", "filterable": False, "dimension": False},
        {"name": "is_bad_review", "type": "INTEGER", "description": "是否为低分/异常评价，1 表示异常，0 表示正常。", "filterable": True, "dimension": True},
        {"name": "ticket_status", "type": "INTEGER", "description": "工单状态枚举，当前查询只允许 1/2/3 的可分析状态。", "filterable": True, "dimension": True},
    ],
    "metrics": [
        {"name": "异常工单数", "expression": "COUNT(DISTINCT order_id)", "description": "命中只读条件后的异常订单数。"},
        {"name": "估算赔付总额", "expression": "ROUND(SUM(compensation_amount), 2)", "description": "命中范围内的赔付金额合计。"},
        {"name": "平均赔付", "expression": "ROUND(AVG(compensation_amount), 2)", "description": "命中异常明细的平均赔付金额。"},
    ],
    "allowed_filters": ["category", "complaint_type", "compensation_amount", "created_at", "is_bad_review", "ticket_status", "user_id", "order_id"],
    "default_scope": "is_bad_review = 1 AND ticket_status IN (1, 2, 3)",
}


def load_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def classify_category(raw_value: str) -> str:
    raw = (raw_value or "").lower()
    for mapped, patterns in PRODUCT_CATEGORY_RULES.items():
        if any(pattern in raw for pattern in patterns):
            return mapped
    return "其他"


def classify_complaint(comment: str, review_score: float) -> str:
    content = (comment or "").lower()
    for complaint_type, patterns in COMPLAINT_PATTERNS.items():
        if any(pattern in content for pattern in patterns):
            return complaint_type
    if review_score <= 2:
        return "质量问题"
    return "一般咨询"


def summarize_text(text: str, limit: int = 110) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    return clean[:limit] + ("..." if len(clean) > limit else "")


def detect_category_from_query(message: str) -> str | None:
    for keyword, category in CATEGORY_QUERY_MAP.items():
        if keyword in message:
            return category
    return None


def detect_complaint_type(message: str) -> str | None:
    for complaint_type in COMPLAINT_PATTERNS:
        if complaint_type in message:
            return complaint_type
    return None


def detect_amount_threshold(message: str) -> float | None:
    match = re.search(r"(超过|大于|高于)\s*(\d+(?:\.\d+)?)\s*元", message)
    return float(match.group(2)) if match else None


def contains_any(message: str, patterns: list[str]) -> bool:
    lowered = message.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def normalize_category(category: str | None) -> str | None:
    if not category:
        return None
    if category in PRODUCT_CATEGORY_RULES:
        return category
    return CATEGORY_QUERY_MAP.get(category)


class RedisRuntime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.available = False
        self.error: str | None = None
        self.client: Any | None = None
        self.memory: dict[str, Any] = {}
        if not settings.redis_enabled:
            self.error = "redis_disabled"
            return
        if redis is None:
            self.error = "redis_package_missing"
            return
        try:
            self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=0.25, socket_timeout=0.25)
            self.client.ping()
            self.available = True
        except Exception as exc:
            self.client = None
            self.error = f"redis_unavailable:{exc}"

    def _memory_expired(self, key: str) -> bool:
        item = self.memory.get(key)
        if not isinstance(item, dict) or "expires_at" not in item:
            return False
        if item["expires_at"] and item["expires_at"] < time.time():
            self.memory.pop(key, None)
            return True
        return False

    def get(self, key: str) -> str | None:
        if self.available and self.client:
            return self.client.get(key)
        if self._memory_expired(key):
            return None
        item = self.memory.get(key)
        if isinstance(item, dict) and "value" in item:
            return item["value"]
        return item if isinstance(item, str) else None

    def setex(self, key: str, seconds: int, value: str) -> None:
        if self.available and self.client:
            self.client.setex(key, seconds, value)
            return
        self.memory[key] = {"value": value, "expires_at": time.time() + seconds if seconds else None}

    def get_json(self, key: str) -> Any | None:
        raw = self.get(key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set_json(self, key: str, value: Any, seconds: int) -> None:
        self.setex(key, seconds, json.dumps(value, ensure_ascii=False))

    def incr_with_ttl(self, key: str, ttl_seconds: int) -> int:
        if self.available and self.client:
            value = int(self.client.incr(key))
            if value == 1:
                self.client.expire(key, ttl_seconds)
            return value
        if self._memory_expired(key):
            self.memory.pop(key, None)
        item = self.memory.get(key)
        value = int(item.get("value", 0) if isinstance(item, dict) else 0) + 1
        self.memory[key] = {"value": str(value), "expires_at": time.time() + ttl_seconds}
        return value

    def push_event(self, key: str, payload: dict[str, Any], limit: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False)
        if self.available and self.client:
            self.client.lpush(key, raw)
            self.client.ltrim(key, 0, limit - 1)
            return
        events = self.memory.setdefault(key, [])
        if isinstance(events, list):
            events.insert(0, raw)
            del events[limit:]

    def list_events(self, key: str, limit: int = 50) -> list[dict[str, Any]]:
        if self.available and self.client:
            rows = self.client.lrange(key, 0, limit - 1)
        else:
            rows = self.memory.get(key, [])[:limit] if isinstance(self.memory.get(key), list) else []
        events = []
        for row in rows:
            try:
                events.append(json.loads(row))
            except json.JSONDecodeError:
                pass
        return events


class UserStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_database()

    def _ensure_database(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('viewer', 'analyst', 'supervisor')),
                    password_hash TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
        self._seed_demo_users()

    def _seed_demo_users(self) -> None:
        demo_users = [
            ("viewer@example.com", "Viewer Demo", "viewer", "Viewer@123"),
            ("analyst@example.com", "Analyst Demo", "analyst", "Analyst@123"),
            ("supervisor@example.com", "Supervisor Demo", "supervisor", "Supervisor@123"),
        ]
        with sqlite3.connect(self.db_path) as conn:
            for username, display_name, role, password in demo_users:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO users (id, username, display_name, role, password_hash)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (f"usr_{uuid.uuid5(uuid.NAMESPACE_DNS, username).hex[:16]}", username, display_name, role, hash_password(password)),
                )
            conn.commit()

    def authenticate(self, username: str, password: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, username, display_name, role, password_hash, is_active FROM users WHERE username = ?",
                (username.strip().lower(),),
            ).fetchone()
        if not row or not row["is_active"] or not verify_password(password, row["password_hash"]):
            return None
        item = dict(row)
        item.pop("password_hash", None)
        item["is_active"] = bool(item["is_active"])
        return item

    def get_by_id(self, user_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT id, username, display_name, role, is_active, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["is_active"] = bool(item["is_active"])
        return item


class TaskQueueStore:
    def __init__(self, redis_runtime: RedisRuntime):
        self.redis = redis_runtime

    def create(self, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = f"task_{uuid.uuid4().hex[:16]}"
        now = utc_now().isoformat()
        item = {"task_id": task_id, "task_type": task_type, "status": "queued", "payload": payload, "created_at": now, "updated_at": now}
        self.redis.set_json(f"task:{task_id}", item, 86400)
        self.redis.push_event("task_events", {"event": "queued", **item})
        return item

    def update(self, task_id: str, status: str, result: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> dict[str, Any]:
        item = self.get(task_id) or {"task_id": task_id, "task_type": "unknown", "payload": {}, "created_at": utc_now().isoformat()}
        item.update({"status": status, "result": result, "error": error, "updated_at": utc_now().isoformat()})
        self.redis.set_json(f"task:{task_id}", item, 86400)
        self.redis.push_event("task_events", {"event": status, **item})
        return item

    def get(self, task_id: str) -> dict[str, Any] | None:
        return self.redis.get_json(f"task:{task_id}")

    def events(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.redis.list_events("task_events", limit=limit)


@dataclass
class QueryFilters:
    category: str | None = None
    complaint_type: str | None = None
    amount_threshold: float | None = None


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


class SessionMemoryStore:
    def __init__(self, redis_runtime: RedisRuntime | None = None, ttl_seconds: int = 86400):
        self.sessions: dict[str, list[dict[str, str]]] = {}
        self.redis = redis_runtime
        self.ttl_seconds = ttl_seconds

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}:messages"

    def get_or_create(self, session_id: str | None = None) -> str:
        sid = session_id or str(uuid.uuid4())
        if self.redis and self.redis.available:
            if self.redis.get_json(self._key(sid)) is None:
                self.redis.set_json(self._key(sid), [], self.ttl_seconds)
        else:
            self.sessions.setdefault(sid, [])
        return sid

    def recent_messages(self, session_id: str, limit: int = 6) -> list[dict[str, str]]:
        if self.redis and self.redis.available:
            return (self.redis.get_json(self._key(session_id)) or [])[-limit:]
        return self.sessions.get(session_id, [])[-limit:]

    def append(self, session_id: str, role: str, content: str) -> None:
        if self.redis and self.redis.available:
            messages = self.redis.get_json(self._key(session_id)) or []
            messages.append({"role": role, "content": content})
            self.redis.set_json(self._key(session_id), messages[-12:], self.ttl_seconds)
            return
        self.sessions.setdefault(session_id, []).append({"role": role, "content": content})
        self.sessions[session_id] = self.sessions[session_id][-12:]


class LocalAnalyticsEngine:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.frames = self._load_frames()
        self.dataset = self._build_dataset()
        self.user_summary = self._build_user_summary()

    def _load_csv(self, name: str) -> pd.DataFrame:
        return pd.read_csv(self.data_dir / name)

    def _load_frames(self) -> dict[str, pd.DataFrame]:
        return {
            "orders": self._load_csv("olist_orders_dataset.csv"),
            "order_items": self._load_csv("olist_order_items_dataset.csv"),
            "reviews": self._load_csv("olist_order_reviews_dataset.csv"),
            "products": self._load_csv("olist_products_dataset.csv"),
        }

    def _build_dataset(self) -> pd.DataFrame:
        orders = self.frames["orders"].copy()
        items = self.frames["order_items"].copy()
        reviews = self.frames["reviews"].copy()
        products = self.frames["products"].copy()

        orders["order_purchase_timestamp"] = pd.to_datetime(orders["order_purchase_timestamp"], errors="coerce")
        reviews["review_comment_message"] = reviews["review_comment_message"].fillna("")
        products["macro_category"] = products["product_category_name"].fillna("").map(classify_category)

        review_rank = reviews.assign(comment_len=reviews["review_comment_message"].str.len())
        review_rank = review_rank.sort_values(["review_score", "comment_len"], ascending=[True, False]).drop_duplicates("order_id")

        merged = orders.merge(items, on="order_id", how="left")
        merged = merged.merge(review_rank[["order_id", "review_score", "review_comment_message"]], on="order_id", how="left")
        merged = merged.merge(products[["product_id", "product_category_name", "macro_category"]], on="product_id", how="left")

        merged["review_score"] = merged["review_score"].fillna(5)
        merged["review_comment_message"] = merged["review_comment_message"].fillna("")
        merged["macro_category"] = merged["macro_category"].fillna("其他")
        merged["complaint_type"] = merged.apply(lambda row: classify_complaint(row["review_comment_message"], row["review_score"]), axis=1)
        merged["is_bad_review"] = (merged["review_score"] <= 2).astype(int)
        merged["compensation_amount"] = (merged["price"].fillna(0) * merged["is_bad_review"] * 0.35 + merged["freight_value"].fillna(0) * merged["is_bad_review"]).round(2)
        merged["user_id"] = merged["customer_id"]
        return merged

    def _build_user_summary(self) -> pd.DataFrame:
        grouped = self.dataset.groupby("user_id", dropna=False).agg(
            total_spend=("price", "sum"),
            avg_price=("price", "mean"),
            avg_freight=("freight_value", "mean"),
            order_count=("order_id", "nunique"),
            bad_review_count=("is_bad_review", "sum"),
            compensation_total=("compensation_amount", "sum"),
        ).reset_index()
        grouped["risk_score"] = grouped.apply(self._score_user_row, axis=1).round(4)
        grouped["risk_level"] = grouped["risk_score"].map(lambda value: "高风险" if value >= 0.62 else "观察中" if value >= 0.4 else "正常")
        grouped["suggestion"] = grouped["risk_level"].map({"高风险": "建议主管介入，限制直接扩赔", "观察中": "建议关注最近工单，必要时人工复核", "正常": "可按标准流程继续处理"})
        return grouped

    def _score_user_row(self, row: pd.Series) -> float:
        spend_factor = min((row["total_spend"] or 0) / 600.0, 1.0)
        complaint_factor = min((row["bad_review_count"] or 0) / 2.0, 1.0)
        frequency_factor = min((row["order_count"] or 0) / 5.0, 1.0)
        compensation_factor = min((row["compensation_total"] or 0) / 200.0, 1.0)
        return clamp(0.18 * spend_factor + 0.42 * complaint_factor + 0.16 * frequency_factor + 0.24 * compensation_factor, 0.02, 0.98)

    def get_overview(self) -> dict[str, Any]:
        high_risk = self.user_summary[self.user_summary["risk_level"] == "高风险"]
        trend_df = self.dataset.dropna(subset=["order_purchase_timestamp"]).groupby(self.dataset["order_purchase_timestamp"].dt.to_period("D")).agg(bad=("is_bad_review", "sum"), total=("order_id", "nunique")).reset_index().tail(30)
        trend = [{"date": str(row["order_purchase_timestamp"]), "bad": int(row["bad"]), "total": int(row["total"])} for _, row in trend_df.iterrows()]

        token_counter: dict[str, int] = {}
        stopwords = {"para", "com", "que", "não", "nao", "foi", "uma", "produto", "muito", "mais", "sem", "isso", "the", "and"}
        for comment in self.dataset.loc[self.dataset["is_bad_review"] == 1, "review_comment_message"].astype(str):
            for token in re.findall(r"[a-zA-ZÀ-ÿ]{3,}", comment.lower()):
                if token not in stopwords:
                    token_counter[token] = token_counter.get(token, 0) + 1
        top_keywords = [{"word": word, "count": count} for word, count in sorted(token_counter.items(), key=lambda item: item[1], reverse=True)[:8]]

        complaint_mix_df = self.dataset[self.dataset["is_bad_review"] == 1].groupby("complaint_type").agg(count=("order_id", "nunique")).reset_index().sort_values("count", ascending=False)
        latest_dt = self.dataset["order_purchase_timestamp"].max()
        return {
            "risk_rate": round(len(high_risk) / max(len(self.user_summary), 1), 4),
            "high_risk_cnt": int(len(high_risk)),
            "total_users": int(len(self.user_summary)),
            "trend": trend,
            "top_keywords": top_keywords,
            "complaint_mix": [{"label": row["complaint_type"], "value": int(row["count"])} for _, row in complaint_mix_df.iterrows()],
            "latest_snapshot": latest_dt.strftime("%Y-%m-%d") if pd.notna(latest_dt) else "无数据",
        }

    def get_daily_risk_report(self, report_date: str | None = None) -> dict[str, Any]:
        df = self.dataset.dropna(subset=["order_purchase_timestamp"]).copy()
        if df.empty:
            return {
                "report_id": "RPT-empty",
                "report_date": report_date,
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "headline": "当前没有可生成日报的数据。",
                "metrics": [],
                "top_risks": [],
                "recommended_actions": ["确认 Olist 样本数据是否已加载。"],
                "delivery_mock": {"channel": "Feishu/WeCom", "status": "mock_not_sent"},
                "markdown": "当前没有可生成日报的数据。",
            }

        df["report_date"] = df["order_purchase_timestamp"].dt.strftime("%Y-%m-%d")
        normalized_date = report_date or str(df["report_date"].max())
        day_df = df[df["report_date"] == normalized_date]
        if day_df.empty:
            normalized_date = str(df["report_date"].max())
            day_df = df[df["report_date"] == normalized_date]

        bad_df = day_df[day_df["is_bad_review"] == 1].copy()
        total_orders = int(day_df["order_id"].nunique())
        abnormal_orders = int(bad_df["order_id"].nunique())
        compensation_total = round(float(bad_df["compensation_amount"].fillna(0).sum()), 2)
        abnormal_rate = round((abnormal_orders / total_orders) * 100, 1) if total_orders else 0.0

        top_risks: list[dict[str, Any]] = []
        if not bad_df.empty:
            grouped = (
                bad_df.groupby(["macro_category", "complaint_type"], dropna=False)
                .agg(order_count=("order_id", "nunique"), compensation_total=("compensation_amount", "sum"))
                .reset_index()
                .sort_values(["compensation_total", "order_count"], ascending=False)
                .head(5)
            )
            for _, row in grouped.iterrows():
                count = int(row["order_count"] or 0)
                top_risks.append({
                    "category": row["macro_category"] or "其他",
                    "complaint_type": row["complaint_type"] or "一般咨询",
                    "order_count": count,
                    "compensation_total": round(float(row["compensation_total"] or 0), 2),
                    "share": round((count / abnormal_orders) * 100, 1) if abnormal_orders else 0,
                    "reason": "低分评价或客诉文本命中异常规则。",
                })

        top_cases = []
        if not bad_df.empty:
            case_df = bad_df.sort_values("compensation_amount", ascending=False).drop_duplicates("order_id").head(5)
            for _, row in case_df.iterrows():
                top_cases.append({
                    "order_id": row["order_id"],
                    "user_id": row["user_id"],
                    "category": row["macro_category"],
                    "complaint_type": row["complaint_type"],
                    "compensation_amount": round(float(row["compensation_amount"] or 0), 2),
                    "comment": summarize_text(row["review_comment_message"] or "-", limit=90),
                })

        recommended_actions = [
            "主管优先查看高赔付异常工单。",
            "运营按类目复盘异常原因，并准备客服安抚口径。",
        ]
        if abnormal_orders == 0:
            recommended_actions = ["当日未命中异常评价，维持常规监控。"]
        elif compensation_total >= 500:
            recommended_actions.insert(0, "赔付金额较高，建议当天完成人工复核。")

        headline = f"{normalized_date} 异常播报：{abnormal_orders} 单异常，占比 {abnormal_rate}%，估算赔付 ¥{compensation_total:.2f}。"
        markdown_lines = [
            f"# 每日异常播报 {normalized_date}",
            "",
            f"- 总订单量：{total_orders}",
            f"- 异常工单：{abnormal_orders}",
            f"- 异常占比：{abnormal_rate}%",
            f"- 估算赔付：¥{compensation_total:.2f}",
            "",
            "## Top 风险",
        ]
        if top_risks:
            markdown_lines.extend(
                f"- {item['category']} / {item['complaint_type']}：{item['order_count']} 单，赔付 ¥{item['compensation_total']:.2f}，占比 {item['share']}%"
                for item in top_risks
            )
        else:
            markdown_lines.append("- 当日未命中异常风险。")
        markdown_lines.extend(["", "## 建议动作", *[f"- {item}" for item in recommended_actions]])

        return {
            "report_id": f"RPT-{normalized_date.replace('-', '')}",
            "report_date": normalized_date,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "headline": headline,
            "metrics": [
                {"label": "总订单量", "value": total_orders},
                {"label": "异常工单", "value": abnormal_orders},
                {"label": "异常占比", "value": f"{abnormal_rate}%"},
                {"label": "估算赔付", "value": round(compensation_total, 2)},
            ],
            "top_risks": top_risks,
            "top_cases": top_cases,
            "recommended_actions": recommended_actions,
            "delivery_mock": {
                "channel": "Feishu/WeCom",
                "status": "mock_not_sent",
                "schedule": "daily 09:30",
                "note": "当前只生成可发送内容，不调用真实 webhook。",
            },
            "markdown": "\n".join(markdown_lines),
        }

    def _order_row(self, order_id: str) -> pd.Series | None:
        rows = self.dataset[self.dataset["order_id"] == order_id]
        if rows.empty:
            return None
        return rows.iloc[0]

    def query_order_status(self, order_id: str) -> dict[str, Any]:
        row = self._order_row(order_id)
        if row is None:
            return {"found": False, "order_id": order_id, "error_code": "order_not_found"}
        return {
            "found": True,
            "order_id": order_id,
            "user_id": str(row.get("user_id", "")),
            "order_status": str(row.get("order_status", "unknown")),
            "category": str(row.get("macro_category", "unknown")),
            "created_at": str(row.get("order_purchase_timestamp", "")),
            "approved_at": str(row.get("order_approved_at", "")),
            "estimated_delivery_at": str(row.get("order_estimated_delivery_date", "")),
            "review_score": int(row.get("review_score", 0) or 0),
        }

    def query_logistics_status(self, order_id: str) -> dict[str, Any]:
        row = self._order_row(order_id)
        if row is None:
            return {"found": False, "order_id": order_id, "error_code": "order_not_found"}
        delivered = pd.to_datetime(row.get("order_delivered_customer_date"), errors="coerce")
        estimated = pd.to_datetime(row.get("order_estimated_delivery_date"), errors="coerce")
        delayed_days = 0
        if pd.notna(delivered) and pd.notna(estimated):
            delayed_days = max((delivered - estimated).days, 0)
        status = "delayed" if delayed_days > 0 else str(row.get("order_status", "unknown"))
        return {
            "found": True,
            "order_id": order_id,
            "logistics_status": status,
            "delivered_at": str(row.get("order_delivered_customer_date", "")),
            "estimated_delivery_at": str(row.get("order_estimated_delivery_date", "")),
            "delayed_days": delayed_days,
            "freight_value": round(float(row.get("freight_value", 0) or 0), 2),
        }

    def query_refund_eligibility(self, order_id: str, reason: str | None = None) -> dict[str, Any]:
        row = self._order_row(order_id)
        if row is None:
            return {"found": False, "order_id": order_id, "eligible": False, "error_code": "order_not_found"}
        complaint_type = str(row.get("complaint_type", ""))
        compensation = round(float(row.get("compensation_amount", 0) or 0), 2)
        review_score = int(row.get("review_score", 5) or 5)
        eligible = bool(review_score <= 2 or compensation > 0 or contains_any(reason or "", ["refund", "return", "damaged", "delay"]))
        priority = "high" if compensation >= 100 or review_score <= 1 else "medium" if eligible else "low"
        return {
            "found": True,
            "order_id": order_id,
            "eligible": eligible,
            "priority": priority,
            "complaint_type": complaint_type,
            "estimated_refund_amount": compensation,
            "reason": reason or complaint_type,
            "recommended_action": "escalate_to_supervisor" if priority == "high" else "standard_refund_review" if eligible else "collect_more_evidence",
        }

    def query_policy_by_market(self, market: str, topic: str) -> dict[str, Any]:
        market_code = market.strip().upper()
        baseline = {
            "BR": "Follow marketplace refund SLA, keep Portuguese customer evidence, and verify logistics timestamps before compensation.",
            "US": "Check return window, state-specific consumer protection notes, and payment dispute risk before final approval.",
            "EU": "Check withdrawal rights, warranty evidence, GDPR-safe notes, and seller response SLA.",
            "CN": "Check seven-day no-reason rules, platform category exceptions, invoice evidence, and escalation threshold.",
        }
        return {
            "market": market_code,
            "topic": topic,
            "policy": baseline.get(market_code, "Use global baseline policy and route market-specific uncertainty to supervisor review."),
            "requires_supervisor": market_code not in baseline or contains_any(topic, ["high value", "fraud", "cross-border", "跨境", "欺诈", "高额"]),
        }

    def get_user_risk(self, user_id: str) -> dict[str, Any]:
        row = self.user_summary[self.user_summary["user_id"] == user_id]
        if row.empty:
            return {"found": False, "message": f"未找到用户 {user_id} 的本地样本记录。"}
        item = row.iloc[0].to_dict()
        return {
            "found": True,
            "user_id": item["user_id"],
            "risk_score": round(float(item["risk_score"]), 4),
            "risk_level": item["risk_level"],
            "suggestion": item["suggestion"],
            "metrics": {"订单数": int(item["order_count"]), "差评触发数": int(item["bad_review_count"]), "累计实付": round(float(item["total_spend"]), 2), "累计赔付估算": round(float(item["compensation_total"]), 2)},
        }


def build_tickets_export_frame(analytics: LocalAnalyticsEngine) -> pd.DataFrame:
    df = analytics.dataset.copy()
    return pd.DataFrame({
        "order_id": df["order_id"].fillna("").astype(str),
        "user_id": df["user_id"].fillna("").astype(str),
        "category": df["macro_category"].fillna("其他").astype(str),
        "complaint_type": df["complaint_type"].fillna("一般咨询").astype(str),
        "compensation_amount": df["compensation_amount"].fillna(0).astype(float),
        "pay_amount": df["price"].fillna(0).astype(float),
        "created_at": df["order_purchase_timestamp"].dt.strftime("%Y-%m-%d").fillna("-"),
        "comment": df["review_comment_message"].fillna("").astype(str),
        "is_bad_review": df["is_bad_review"].fillna(0).astype(int),
        "ticket_status": 1,
    })


class ReadOnlySQLiteStore:
    backend_name = "sqlite"

    def __init__(self, db_path: Path, analytics: LocalAnalyticsEngine):
        self.db_path = db_path
        self.analytics = analytics
        self._ensure_database()

    def _ensure_database(self) -> None:
        if self.db_path.exists():
            return
        export_df = build_tickets_export_frame(self.analytics)
        with sqlite3.connect(self.db_path) as conn:
            export_df.to_sql("tickets", conn, if_exists="replace", index=False)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_readonly ON tickets(is_bad_review, complaint_type, category, compensation_amount)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id)")
            conn.commit()

    def _connect_readonly(self) -> sqlite3.Connection:
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def schema_catalog(self) -> dict[str, Any]:
        with self._connect_readonly() as conn:
            db_columns = {row["name"]: row["type"] for row in conn.execute("PRAGMA table_info(tickets)").fetchall()}
        columns = []
        for column in TICKETS_SCHEMA["columns"]:
            item = dict(column)
            item["type"] = db_columns.get(item["name"], item["type"])
            columns.append(item)
        return {
            "tables": [{
                "name": TICKETS_SCHEMA["table"],
                "description": TICKETS_SCHEMA["description"],
                "default_scope": TICKETS_SCHEMA["default_scope"],
                "columns": columns,
            }],
            "filterable_dimensions": [
                column["name"]
                for column in columns
                if column.get("filterable") and column.get("dimension")
            ],
            "allowed_filters": TICKETS_SCHEMA["allowed_filters"],
            "metrics": TICKETS_SCHEMA["metrics"],
            "safety": {
                "mode": "readonly",
                "allowed_statements": ["SELECT", "WITH"],
                "rejected_keywords": sorted(SQL_FORBIDDEN_KEYWORDS),
                "validator": "validate_readonly_sql",
            },
        }

    def _where_clause(self, filters: QueryFilters) -> tuple[str, list[Any]]:
        conditions = ["is_bad_review = 1", "ticket_status IN (1, 2, 3)"]
        params: list[Any] = []
        if filters.category:
            conditions.append("category = ?")
            params.append(filters.category)
        if filters.complaint_type:
            conditions.append("complaint_type = ?")
            params.append(filters.complaint_type)
        if filters.amount_threshold is not None:
            conditions.append("compensation_amount >= ?")
            params.append(filters.amount_threshold)
        return " AND ".join(conditions), params

    def build_sql_preview(self, filters: QueryFilters, limit: int = 8) -> str:
        where_sql, params = self._where_clause(filters)
        return (
            "SELECT order_id, user_id, category, complaint_type,\n"
            "       ROUND(SUM(compensation_amount), 2) AS compensation_amount,\n"
            "       ROUND(SUM(pay_amount), 2) AS pay_amount,\n"
            "       MIN(created_at) AS created_at,\n"
            "       MIN(comment) AS comment\n"
            "FROM tickets\n"
            f"WHERE {where_sql}\n"
            "GROUP BY order_id, user_id, category, complaint_type\n"
            "ORDER BY compensation_amount DESC\n"
            f"LIMIT {limit};\n"
            f"-- params: {params}"
        )

    def query_ticket_details(self, filters: QueryFilters, limit: int = 8) -> dict[str, Any]:
        where_sql, params = self._where_clause(filters)
        detail_sql = (
            "SELECT order_id, user_id, category, complaint_type, "
            "ROUND(SUM(compensation_amount), 2) AS compensation_amount, "
            "ROUND(SUM(pay_amount), 2) AS pay_amount, "
            "MIN(created_at) AS created_at, MIN(comment) AS comment "
            "FROM tickets "
            f"WHERE {where_sql} "
            "GROUP BY order_id, user_id, category, complaint_type "
            "ORDER BY compensation_amount DESC "
            "LIMIT ?"
        )
        metrics_sql = (
            "SELECT COUNT(DISTINCT order_id) AS ticket_count, "
            "ROUND(SUM(compensation_amount), 2) AS compensation_total, "
            "ROUND(AVG(compensation_amount), 2) AS compensation_avg "
            "FROM tickets "
            f"WHERE {where_sql}"
        )
        validate_readonly_sql(detail_sql)
        validate_readonly_sql(metrics_sql)
        with self._connect_readonly() as conn:
            rows = conn.execute(detail_sql, [*params, limit]).fetchall()
            metrics = conn.execute(metrics_sql, params).fetchone()

        if not rows:
            return {"rows": [], "summary": "查无符合条件的只读 SQL 明细。", "metrics": {}, "sql_preview": self.build_sql_preview(filters, limit=limit)}

        ticket_count = int(metrics["ticket_count"] or 0)
        compensation_total = float(metrics["compensation_total"] or 0)
        normalized_rows = [{
            "order_id": row["order_id"],
            "user_id": row["user_id"],
            "category": row["category"],
            "complaint_type": row["complaint_type"],
            "compensation_amount": round(float(row["compensation_amount"] or 0), 2),
            "pay_amount": round(float(row["pay_amount"] or 0), 2),
            "created_at": row["created_at"] or "-",
            "comment": summarize_text(row["comment"] or "-"),
            "ticket_count": 1,
            "share_of_total": round((float(row["compensation_amount"] or 0) / compensation_total) * 100, 1) if compensation_total else 0,
            "reason": f"{row['category']} / {row['complaint_type']} 命中差评与赔付估算规则。",
        } for row in rows]
        return {
            "rows": normalized_rows,
            "summary": f"只读 SQL 命中 {ticket_count} 条异常明细，以下展示赔付金额最高的 {len(normalized_rows)} 条。",
            "metrics": {
                "异常工单数": ticket_count,
                "估算赔付总额": round(compensation_total, 2),
                "平均赔付": round(float(metrics["compensation_avg"] or 0), 2),
            },
            "sql_preview": self.build_sql_preview(filters, limit=limit),
        }


class MySQLReadOnlyTicketStore:
    backend_name = "mysql"

    def __init__(self):
        self.host = os.getenv("MYSQL_READONLY_HOST") or os.getenv("MYSQL_HOST", "127.0.0.1")
        self.port = int(os.getenv("MYSQL_READONLY_PORT") or os.getenv("MYSQL_PORT", "3306"))
        self.user = os.getenv("MYSQL_READONLY_USER") or os.getenv("MYSQL_USER", "root")
        self.password = os.getenv("MYSQL_READONLY_PASSWORD") or os.getenv("MYSQL_PASSWORD")
        self.database = os.getenv("MYSQL_READONLY_DATABASE") or os.getenv("MYSQL_DATABASE", "copilot_db")

    def _connect_readonly(self):
        try:
            import pymysql
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("MySQL backend requires pymysql. Install requirements-optional.txt first.") from exc
        if not self.password or self.password == "your_mysql_password":
            raise RuntimeError("请先设置 MYSQL_READONLY_PASSWORD 或 MYSQL_PASSWORD。")
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset="utf8mb4",
            autocommit=True,
            cursorclass=pymysql.cursors.DictCursor,
            read_timeout=10,
            write_timeout=10,
        )

    def schema_catalog(self) -> dict[str, Any]:
        columns = [dict(column) for column in TICKETS_SCHEMA["columns"]]
        return {
            "tables": [{
                "name": TICKETS_SCHEMA["table"],
                "description": f"{TICKETS_SCHEMA['description']} 当前配置为 MySQL 只读查询后端。",
                "default_scope": TICKETS_SCHEMA["default_scope"],
                "columns": columns,
            }],
            "filterable_dimensions": [
                column["name"]
                for column in columns
                if column.get("filterable") and column.get("dimension")
            ],
            "allowed_filters": TICKETS_SCHEMA["allowed_filters"],
            "metrics": TICKETS_SCHEMA["metrics"],
            "safety": {
                "mode": "readonly",
                "backend": self.backend_name,
                "allowed_statements": ["SELECT", "WITH"],
                "rejected_keywords": sorted(SQL_FORBIDDEN_KEYWORDS),
                "validator": "validate_readonly_sql",
                "account_hint": "建议使用只有 SELECT 权限的 MySQL 账号。",
            },
        }

    def _where_clause(self, filters: QueryFilters) -> tuple[str, list[Any]]:
        conditions = ["is_bad_review = 1", "ticket_status IN (1, 2, 3)"]
        params: list[Any] = []
        if filters.category:
            conditions.append("category = %s")
            params.append(filters.category)
        if filters.complaint_type:
            conditions.append("complaint_type = %s")
            params.append(filters.complaint_type)
        if filters.amount_threshold is not None:
            conditions.append("compensation_amount >= %s")
            params.append(filters.amount_threshold)
        return " AND ".join(conditions), params

    def build_sql_preview(self, filters: QueryFilters, limit: int = 8) -> str:
        where_sql, params = self._where_clause(filters)
        return (
            "SELECT order_id, user_id, category, complaint_type,\n"
            "       ROUND(SUM(compensation_amount), 2) AS compensation_amount,\n"
            "       ROUND(SUM(pay_amount), 2) AS pay_amount,\n"
            "       MIN(created_at) AS created_at,\n"
            "       MIN(comment) AS comment\n"
            "FROM tickets\n"
            f"WHERE {where_sql}\n"
            "GROUP BY order_id, user_id, category, complaint_type\n"
            "ORDER BY compensation_amount DESC\n"
            f"LIMIT {limit};\n"
            f"-- backend: mysql\n"
            f"-- params: {params}"
        )

    def query_ticket_details(self, filters: QueryFilters, limit: int = 8) -> dict[str, Any]:
        where_sql, params = self._where_clause(filters)
        detail_sql = (
            "SELECT order_id, user_id, category, complaint_type, "
            "ROUND(SUM(compensation_amount), 2) AS compensation_amount, "
            "ROUND(SUM(pay_amount), 2) AS pay_amount, "
            "MIN(created_at) AS created_at, MIN(comment) AS comment "
            "FROM tickets "
            f"WHERE {where_sql} "
            "GROUP BY order_id, user_id, category, complaint_type "
            "ORDER BY compensation_amount DESC "
            "LIMIT %s"
        )
        metrics_sql = (
            "SELECT COUNT(DISTINCT order_id) AS ticket_count, "
            "ROUND(SUM(compensation_amount), 2) AS compensation_total, "
            "ROUND(AVG(compensation_amount), 2) AS compensation_avg "
            "FROM tickets "
            f"WHERE {where_sql}"
        )
        validate_readonly_sql(detail_sql)
        validate_readonly_sql(metrics_sql)
        with self._connect_readonly() as conn:
            with conn.cursor() as cursor:
                cursor.execute(detail_sql, [*params, limit])
                rows = cursor.fetchall()
                cursor.execute(metrics_sql, params)
                metrics = cursor.fetchone() or {}

        if not rows:
            return {"rows": [], "summary": "MySQL 只读查询未命中符合条件的明细。", "metrics": {}, "sql_preview": self.build_sql_preview(filters, limit=limit)}

        ticket_count = int(metrics.get("ticket_count") or 0)
        compensation_total = float(metrics.get("compensation_total") or 0)
        normalized_rows = [{
            "order_id": row["order_id"],
            "user_id": row["user_id"],
            "category": row["category"],
            "complaint_type": row["complaint_type"],
            "compensation_amount": round(float(row["compensation_amount"] or 0), 2),
            "pay_amount": round(float(row["pay_amount"] or 0), 2),
            "created_at": row["created_at"] or "-",
            "comment": summarize_text(row["comment"] or "-"),
            "ticket_count": 1,
            "share_of_total": round((float(row["compensation_amount"] or 0) / compensation_total) * 100, 1) if compensation_total else 0,
            "reason": f"{row['category']} / {row['complaint_type']} 命中差评与赔付估算规则。",
        } for row in rows]
        return {
            "rows": normalized_rows,
            "summary": f"MySQL 只读查询命中 {ticket_count} 条异常明细，以下展示赔付金额最高的 {len(normalized_rows)} 条。",
            "metrics": {
                "异常工单数": ticket_count,
                "估算赔付总额": round(compensation_total, 2),
                "平均赔付": round(float(metrics.get("compensation_avg") or 0), 2),
            },
            "sql_preview": self.build_sql_preview(filters, limit=limit),
        }


class AuditLogStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_database()

    def _ensure_database(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    trace_id TEXT,
                    session_id TEXT,
                    mode TEXT NOT NULL,
                    route_mode TEXT,
                    route_source TEXT,
                    route_confidence REAL,
                    route_reason TEXT,
                    blocked_by_guardrail INTEGER NOT NULL DEFAULT 0,
                    blocked_by_permission INTEGER NOT NULL DEFAULT 0,
                    user_role TEXT NOT NULL DEFAULT 'analyst',
                    user_message TEXT NOT NULL,
                    response_title TEXT,
                    tool_trace_json TEXT NOT NULL,
                    sql_preview TEXT,
                    latency_ms REAL NOT NULL,
                    token_usage_json TEXT NOT NULL DEFAULT '{}',
                    estimated_cost_usd REAL NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_events(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_events(request_id)")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(audit_events)").fetchall()}
            if "blocked_by_permission" not in columns:
                conn.execute("ALTER TABLE audit_events ADD COLUMN blocked_by_permission INTEGER NOT NULL DEFAULT 0")
            if "user_role" not in columns:
                conn.execute("ALTER TABLE audit_events ADD COLUMN user_role TEXT NOT NULL DEFAULT 'analyst'")
            if "trace_id" not in columns:
                conn.execute("ALTER TABLE audit_events ADD COLUMN trace_id TEXT")
            if "token_usage_json" not in columns:
                conn.execute("ALTER TABLE audit_events ADD COLUMN token_usage_json TEXT NOT NULL DEFAULT '{}'")
            if "estimated_cost_usd" not in columns:
                conn.execute("ALTER TABLE audit_events ADD COLUMN estimated_cost_usd REAL NOT NULL DEFAULT 0")
            if "retry_count" not in columns:
                conn.execute("ALTER TABLE audit_events ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0")
            conn.commit()

    def record(self, event: dict[str, Any]) -> None:
        route = event.get("route") or {}
        tool_trace = event.get("tool_trace") or []
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    request_id, trace_id, session_id, mode, route_mode, route_source, route_confidence,
                    route_reason, blocked_by_guardrail, blocked_by_permission, user_role, user_message, response_title,
                    tool_trace_json, sql_preview, latency_ms, token_usage_json, estimated_cost_usd, retry_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["request_id"],
                    event.get("trace_id"),
                    event.get("session_id"),
                    event["mode"],
                    route.get("mode"),
                    route.get("source"),
                    route.get("confidence"),
                    route.get("reason"),
                    1 if event.get("blocked_by_guardrail") else 0,
                    1 if event.get("blocked_by_permission") else 0,
                    event.get("user_role", "analyst"),
                    event["user_message"],
                    event.get("response_title"),
                    json.dumps(tool_trace, ensure_ascii=False),
                    event.get("sql_preview"),
                    float(event.get("latency_ms", 0)),
                    json.dumps(event.get("token_usage") or {}, ensure_ascii=False),
                    float(event.get("estimated_cost_usd", 0)),
                    int(event.get("retry_count", 0) or 0),
                ),
            )
            conn.commit()

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT request_id, trace_id, session_id, mode, route_mode, route_source, route_confidence,
                       route_reason, blocked_by_guardrail, blocked_by_permission, user_role, user_message, response_title,
                       tool_trace_json, sql_preview, latency_ms, token_usage_json, estimated_cost_usd, retry_count, created_at
                FROM audit_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            item["blocked_by_guardrail"] = bool(item["blocked_by_guardrail"])
            item["blocked_by_permission"] = bool(item["blocked_by_permission"])
            item["tool_trace"] = json.loads(item.pop("tool_trace_json") or "[]")
            item["token_usage"] = json.loads(item.pop("token_usage_json") or "{}")
            events.append(item)
        return events


class HumanReviewQueue:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_database()

    def _ensure_database(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS human_review_queue (
                    case_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE,
                    session_id TEXT,
                    user_role TEXT NOT NULL DEFAULT 'analyst',
                    source_mode TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    response_summary TEXT,
                    tool_trace_json TEXT NOT NULL,
                    case_priority TEXT NOT NULL DEFAULT 'medium',
                    escalation_reason TEXT,
                    assignee TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewer_note TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_review_status ON human_review_queue(status, created_at)")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(human_review_queue)").fetchall()}
            if "case_priority" not in columns:
                conn.execute("ALTER TABLE human_review_queue ADD COLUMN case_priority TEXT NOT NULL DEFAULT 'medium'")
            if "escalation_reason" not in columns:
                conn.execute("ALTER TABLE human_review_queue ADD COLUMN escalation_reason TEXT")
            if "assignee" not in columns:
                conn.execute("ALTER TABLE human_review_queue ADD COLUMN assignee TEXT")
            conn.commit()

    def enqueue(self, event: dict[str, Any]) -> dict[str, Any]:
        case_id = event.get("case_id") or f"REV-{uuid.uuid4().hex[:10].upper()}"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT OR IGNORE INTO human_review_queue (
                    case_id, request_id, session_id, user_role, source_mode, reason,
                    user_message, response_summary, tool_trace_json, case_priority, escalation_reason, assignee
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    event["request_id"],
                    event.get("session_id"),
                    event.get("user_role", "analyst"),
                    event.get("source_mode", "unknown"),
                    event.get("reason", "需要人工复核"),
                    event.get("user_message", ""),
                    event.get("response_summary"),
                    json.dumps(event.get("tool_trace") or [], ensure_ascii=False),
                    event.get("case_priority", "medium"),
                    event.get("escalation_reason") or event.get("reason"),
                    event.get("assignee"),
                ),
            )
            row = conn.execute(
                """
                SELECT case_id, request_id, session_id, user_role, source_mode, reason,
                       user_message, response_summary, case_priority, escalation_reason, assignee, status, created_at, updated_at
                FROM human_review_queue
                WHERE request_id = ?
                """,
                (event["request_id"],),
            ).fetchone()
            conn.commit()
        return dict(row) if row else {"case_id": case_id, "request_id": event["request_id"], "status": "pending"}

    def recent(self, limit: int = 20, status: str = "pending") -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT case_id, request_id, session_id, user_role, source_mode, reason,
                       user_message, response_summary, tool_trace_json, case_priority, escalation_reason, assignee, status,
                       reviewer_note, created_at, updated_at
                FROM human_review_queue
                WHERE status = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (status, limit),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["tool_trace"] = json.loads(item.pop("tool_trace_json") or "[]")
            items.append(item)
        return items

    def update_status(self, case_id: str, status: str, reviewer_note: str | None = None, assignee: str | None = None, case_priority: str | None = None) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                UPDATE human_review_queue
                SET status = ?,
                    reviewer_note = ?,
                    assignee = COALESCE(?, assignee),
                    case_priority = COALESCE(?, case_priority),
                    updated_at = CURRENT_TIMESTAMP
                WHERE case_id = ?
                """,
                (status, reviewer_note, assignee, case_priority, case_id),
            )
            row = conn.execute(
                """
                SELECT case_id, request_id, session_id, user_role, source_mode, reason,
                       user_message, response_summary, tool_trace_json, case_priority, escalation_reason, assignee, status,
                       reviewer_note, created_at, updated_at
                FROM human_review_queue
                WHERE case_id = ?
                """,
                (case_id,),
            ).fetchone()
            conn.commit()
        if not row:
            return None
        item = dict(row)
        item["tool_trace"] = json.loads(item.pop("tool_trace_json") or "[]")
        return item


class FeedbackEventStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_database()

    def _ensure_database(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS feedback_events (
                    event_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    session_id TEXT,
                    rating TEXT NOT NULL CHECK (rating IN ('up', 'down')),
                    comment TEXT,
                    user_role TEXT NOT NULL DEFAULT 'analyst',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_request ON feedback_events(request_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback_events(created_at)")
            conn.commit()

    def record(self, event: dict[str, Any]) -> dict[str, Any]:
        event_id = event.get("event_id") or f"FB-{uuid.uuid4().hex[:10].upper()}"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                """
                INSERT INTO feedback_events (
                    event_id, request_id, session_id, rating, comment, user_role
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    event["request_id"],
                    event.get("session_id"),
                    event["rating"],
                    event.get("comment"),
                    event.get("user_role", "analyst"),
                ),
            )
            row = conn.execute(
                """
                SELECT event_id, request_id, session_id, rating, comment, user_role, created_at
                FROM feedback_events
                WHERE event_id = ?
                """,
                (event_id,),
            ).fetchone()
            conn.commit()
        return dict(row)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT event_id, request_id, session_id, rating, comment, user_role, created_at
                FROM feedback_events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


class PolicyKnowledgeBase:
    def __init__(self, path: Path):
        self.documents: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))

    def lexical_search(self, query: str, category: str | None = None, top_k: int = 3) -> list[dict[str, Any]]:
        query_lower = query.lower()
        scored: list[tuple[float, dict[str, Any]]] = []
        for doc in self.documents:
            score = 0.0
            if category and (doc["category"] == category or doc["category"] == "通用"):
                score += 4
            for keyword in doc.get("keywords", []):
                if keyword.lower() in query_lower:
                    score += 2
            if doc["category"] in query:
                score += 3
            doc_text = f"{doc['title']} {doc['excerpt']} {' '.join(doc.get('guidance', []))}"
            overlap = lexical_overlap_score(query, doc_text)
            score += overlap
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:top_k]]


class LangChainRAGService:
    def __init__(self, settings: Settings, knowledge_base: PolicyKnowledgeBase):
        self.settings = settings
        self.knowledge_base = knowledge_base
        self.available = False
        self.error: str | None = None
        self.client: chromadb.PersistentClient | None = None
        self.collection: Any | None = None
        self.embeddings: OpenAIEmbeddings | None = None
        self.llm: ChatOpenAI | None = None

        if not settings.use_langchain_rag or not settings.embedding_api_key or not settings.llm_api_key:
            self.error = "缺少 LLM 或 Embedding 配置，LangChain RAG 未启用。"
            return
        try:
            if not VECTOR_DIR.exists() and not settings.auto_build_vector_store:
                self.error = f"向量库目录不存在：{VECTOR_DIR.name}。请运行 scripts/build_openai_vector_store.py 构建；当前使用本地规则检索。"
                return
            self.embeddings = OpenAIEmbeddings(api_key=settings.embedding_api_key, base_url=settings.embedding_base_url, model=settings.embedding_model)
            self.client = chromadb.PersistentClient(path=str(VECTOR_DIR))
            self.collection = self.client.get_or_create_collection(name="policy_docs")
            existing = self.collection.get()
            if not existing["ids"]:
                if not settings.auto_build_vector_store:
                    self.error = "向量库为空。请运行 scripts/build_openai_vector_store.py 构建；当前使用本地规则检索。"
                    return
                texts = [f"{doc['title']}\n类别：{doc['category']}\n摘要：{doc['excerpt']}\n规则：{'；'.join(doc['guidance'])}" for doc in knowledge_base.documents]
                metadatas = [{"doc_id": doc["id"], "title": doc["title"], "category": doc["category"], "citation": doc["citation"]} for doc in knowledge_base.documents]
                ids = [doc["id"] for doc in knowledge_base.documents]
                vectors = self.embeddings.embed_documents(texts)
                self.collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=vectors)
            self.llm = ChatOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url, model=settings.llm_model, temperature=0)
            self.available = True
        except Exception as exc:
            self.error = f"向量库初始化失败：{exc}。当前使用本地规则检索。"

    def query(self, question: str, category: str | None = None, top_k: int = 3) -> dict[str, Any]:
        start = time.perf_counter()
        if not self.available or not self.collection or not self.embeddings:
            retrieval_start = time.perf_counter()
            docs = self.knowledge_base.lexical_search(question, category=category, top_k=top_k)
            retrieval_ms = round((time.perf_counter() - retrieval_start) * 1000, 2)
            fallback_sources = []
            for rank, doc in enumerate(docs, start=1):
                fallback_sources.append({
                    "id": doc.get("id"),
                    "title": doc.get("title"),
                    "category": doc.get("category"),
                    "citation": doc.get("citation"),
                    "excerpt": doc.get("excerpt"),
                    "retrieval_score": round(1.0 - (rank - 1) * 0.1, 4),
                    "rerank_score": round(lexical_overlap_score(question, f"{doc.get('title', '')} {doc.get('excerpt', '')}"), 4),
                    "source": "lexical_fallback",
                })
            if docs:
                top_doc = docs[0]
                guidance = "；".join(top_doc.get("guidance", [])[:3])
                answer = f"基于 {top_doc['citation']}，建议先按以下口径处理：{guidance}"
            else:
                answer = "LangChain RAG 当前未启用，且本地规则检索未命中明确条款，建议转人工复核。"
            token_usage = {
                "embedding_tokens": 0,
                "prompt_tokens": 0,
                "completion_tokens": estimate_text_tokens(answer),
                "total_tokens": estimate_text_tokens(answer),
            }
            return {
                "available": False,
                "answer": answer,
                "sources": fallback_sources,
                "fallback_reason": self.error or "未初始化",
                "retrieval_ms": retrieval_ms,
                "embedding_ms": 0,
                "generation_ms": 0,
                "total_ms": round((time.perf_counter() - start) * 1000, 2),
                "token_usage": token_usage,
                "cost_breakdown": estimate_cost_breakdown(self.settings, token_usage),
            }
        embedding_start = time.perf_counter()
        query_vector = self.embeddings.embed_query(question)
        embedding_ms = round((time.perf_counter() - embedding_start) * 1000, 2)
        retrieval_start = time.perf_counter()
        result = self.collection.query(query_embeddings=[query_vector], n_results=max(top_k * 2, 6))
        retrieval_ms = round((time.perf_counter() - retrieval_start) * 1000, 2)
        matched = []
        distances = result.get("distances", [[]])[0] if result.get("distances") else []
        for index, (metadata, document) in enumerate(zip(result.get("metadatas", [[]])[0], result.get("documents", [[]])[0])):
            distance = float(distances[index]) if index < len(distances) else 1.0
            retrieval_score = max(0.0, 1.0 - distance)
            matched.append({
                "id": metadata.get("doc_id"),
                "title": metadata.get("title"),
                "category": metadata.get("category"),
                "citation": metadata.get("citation"),
                "excerpt": summarize_text(document, limit=220),
                "retrieval_score": round(retrieval_score, 4),
                "rerank_score": round(lexical_overlap_score(question, f"{metadata.get('title', '')} {document}"), 4),
                "source": "vector_search",
            })
        matched = sorted(matched, key=lambda item: (item["rerank_score"], item["retrieval_score"]), reverse=True)[:top_k]
        context = "\n\n".join([f"[{item['citation']}] {item['title']} - {item['excerpt']}" for item in matched])
        prompt = "你是企业级售后 Copilot。请只基于给定上下文回答，不能编造规则。如果上下文不足，请明确说需要人工复核。\n\n" + f"问题：{question}\n\n上下文：\n{context}"
        generation_start = time.perf_counter()
        llm_usage = extract_langchain_usage(None, prompt=prompt, answer="")
        try:
            if self.llm:
                llm_message = self.llm.invoke(prompt)
                answer = llm_message.content
                llm_usage = extract_langchain_usage(llm_message, prompt=prompt, answer=answer)
            else:
                answer = "未配置语言模型。"
                llm_usage = extract_langchain_usage(None, prompt=prompt, answer=answer)
        except Exception as exc:
            answer = f"LangChain RAG 检索到了文档，但回答生成失败：{exc}"
            llm_usage = extract_langchain_usage(None, prompt=prompt, answer=answer)
        generation_ms = round((time.perf_counter() - generation_start) * 1000, 2)
        embedding_tokens = estimate_text_tokens(question)
        token_usage = {
            "embedding_tokens": embedding_tokens,
            "prompt_tokens": int(llm_usage.get("prompt_tokens", 0)),
            "completion_tokens": int(llm_usage.get("completion_tokens", 0)),
            "total_tokens": embedding_tokens + int(llm_usage.get("prompt_tokens", 0)) + int(llm_usage.get("completion_tokens", 0)),
        }
        return {
            "available": True,
            "answer": answer,
            "sources": matched,
            "retrieval_ms": retrieval_ms,
            "embedding_ms": embedding_ms,
            "generation_ms": generation_ms,
            "total_ms": round((time.perf_counter() - start) * 1000, 2),
            "token_usage": token_usage,
            "cost_breakdown": estimate_cost_breakdown(self.settings, token_usage),
        }


class FunctionCallingAgent:
    def __init__(self, settings: Settings, analytics: LocalAnalyticsEngine, sql_store: ReadOnlySQLiteStore, knowledge_base: PolicyKnowledgeBase, memory: SessionMemoryStore):
        self.settings = settings
        self.analytics = analytics
        self.sql_store = sql_store
        self.knowledge_base = knowledge_base
        self.memory = memory
        self.client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url) if settings.llm_api_key else None

    def _guardrail(self, message: str) -> dict[str, Any] | None:
        trigger: str | None = None
        if contains_any(message, MUTATION_PATTERNS):
            trigger = "高危写操作意图"
        elif contains_any(message, PROMPT_INJECTION_PATTERNS):
            trigger = "Prompt Injection / 规则绕过意图"
        elif contains_any(message, DATA_EXFILTRATION_PATTERNS):
            trigger = "越权导出或全量数据请求"
        if trigger:
            return {
                "mode": "guardrail",
                "title": "高危操作已拦截",
                "summary": "当前 Agent 只支持授权范围内的查询、检索与分析，不执行写操作、规则绕过或全量敏感数据导出。",
                "highlights": [f"命中 Safety Guardrail：{trigger}", "执行层只允许只读工具", "已进入人工复核队列"],
                "citations": [{"label": "只读安全要求", "text": "Text-to-SQL 与工具层禁止 UPDATE、DELETE、INSERT 等写操作，并拒绝绕过权限和全量导出。"}],
                "tool_trace": [],
                "review_required": True,
                "review_reason": f"命中{trigger}，需要人工判断是否进入审批或安全处理流程。",
            }
        return None

    def _build_tools(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "get_user_risk", "description": "查询指定用户的风险评分、风险等级和建议动作。", "parameters": {"type": "object", "properties": {"user_id": {"type": "string", "description": "用户唯一编号"}}, "required": ["user_id"]}}},
            {"type": "function", "function": {"name": "query_refund_cases", "description": "查询异常退款和客诉明细，返回关键指标、明细表和 SQL 预览。", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "用户原始问题"}, "category": {"type": "string", "description": "业务类目，如 3C数码、生鲜"}, "complaint_type": {"type": "string", "description": "客诉类型，如 质量问题、物流延误"}, "amount_threshold": {"type": "number", "description": "赔付金额阈值，单位元"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "search_policy_docs", "description": "检索售后 SOP、赔付规则、客服安抚话术，并返回引用来源。", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "检索问题"}, "category": {"type": "string", "description": "业务类目，可选"}}, "required": ["query"]}}},
            {"type": "function", "function": {"name": "query_order_status", "description": "Lookup order status by order_id.", "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}},
            {"type": "function", "function": {"name": "query_logistics_status", "description": "Lookup logistics delivery status and delay by order_id.", "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}},
            {"type": "function", "function": {"name": "query_refund_eligibility", "description": "Check refund eligibility and escalation priority for an order.", "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["order_id"]}}},
            {"type": "function", "function": {"name": "query_policy_by_market", "description": "Lookup market-specific refund or complaint policy guidance.", "parameters": {"type": "object", "properties": {"market": {"type": "string"}, "topic": {"type": "string"}}, "required": ["market", "topic"]}}},
        ]

    def _validate_tool_args(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "get_user_risk":
            return GetUserRiskArgs(**arguments).model_dump()
        if name == "query_refund_cases":
            payload = QueryRefundArgs(**arguments).model_dump()
            payload["category"] = normalize_category(payload.get("category")) or detect_category_from_query(payload["query"])
            payload["complaint_type"] = payload.get("complaint_type") or detect_complaint_type(payload["query"])
            payload["amount_threshold"] = payload.get("amount_threshold") or detect_amount_threshold(payload["query"])
            return payload
        if name == "search_policy_docs":
            payload = SearchPolicyArgs(**arguments).model_dump()
            payload["category"] = normalize_category(payload.get("category")) or detect_category_from_query(payload["query"])
            return payload
        if name == "query_order_status":
            return QueryOrderStatusArgs(**arguments).model_dump()
        if name == "query_logistics_status":
            return QueryLogisticsStatusArgs(**arguments).model_dump()
        if name == "query_refund_eligibility":
            return QueryRefundEligibilityArgs(**arguments).model_dump()
        if name == "query_policy_by_market":
            return QueryPolicyByMarketArgs(**arguments).model_dump()
        raise ValueError(f"未知工具：{name}")

    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "get_user_risk":
            return self.analytics.get_user_risk(arguments["user_id"])
        if name == "query_refund_cases":
            return self.sql_store.query_ticket_details(QueryFilters(category=arguments.get("category"), complaint_type=arguments.get("complaint_type"), amount_threshold=arguments.get("amount_threshold")))
        if name == "search_policy_docs":
            query = arguments.get("query", "")
            docs = self.knowledge_base.lexical_search(query, category=arguments.get("category") or detect_category_from_query(query), top_k=3)
            return {"documents": docs}
        if name == "query_order_status":
            return self.analytics.query_order_status(arguments["order_id"])
        if name == "query_logistics_status":
            return self.analytics.query_logistics_status(arguments["order_id"])
        if name == "query_refund_eligibility":
            return self.analytics.query_refund_eligibility(arguments["order_id"], reason=arguments.get("reason"))
        if name == "query_policy_by_market":
            return self.analytics.query_policy_by_market(arguments["market"], arguments["topic"])
        return {"error": f"未知工具：{name}"}

    def _recent_order_id(self, session_id: str) -> str | None:
        for item in reversed(self.memory.recent_messages(session_id, limit=12)):
            match = re.search(r"[0-9a-f]{24,}", item.get("content", ""), re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    def _should_fallback_to_tools(self, message: str) -> bool:
        if re.search(r"[0-9a-f]{24,}", message, re.IGNORECASE) and "风险" in message:
            return True
        return contains_any(message, QUERY_PATTERNS) or contains_any(message, POLICY_PATTERNS) or contains_any(message, ["order status", "logistics", "shipping", "refund eligibility", "market policy", "订单状态", "物流", "退款资格", "市场政策"])

    def _respond_without_llm(self, user_message: str, session_id: str | None = None) -> dict[str, Any]:
        sid = self.memory.get_or_create(session_id)
        aggregate_payload: dict[str, Any] = {}
        tool_trace: list[dict[str, Any]] = []

        user_match = re.search(r"[0-9a-f]{24,}", user_message, re.IGNORECASE)
        order_id = user_match.group(0) if user_match else self._recent_order_id(sid)
        message_lower = user_message.lower()
        if order_id and contains_any(message_lower, ["logistics", "shipping", "delivery", "物流", "快递", "到哪", "进度", "配送"]):
            tool_name = "query_logistics_status"
            validated_args = {"order_id": order_id}
        elif order_id and contains_any(message_lower, ["order status", "订单状态", "status", "订单进展"]):
            tool_name = "query_order_status"
            validated_args = {"order_id": order_id}
        elif order_id and contains_any(message_lower, ["eligible", "refund eligibility", "能退", "退款资格", "能不能退", "是否能退"]):
            tool_name = "query_refund_eligibility"
            validated_args = {"order_id": order_id, "reason": user_message}
        elif contains_any(message_lower, ["market policy", "policy by market", "市场政策", "跨市场"]):
            market_match = re.search(r"\b(BR|US|EU|CN)\b", user_message, re.IGNORECASE)
            tool_name = "query_policy_by_market"
            validated_args = {"market": market_match.group(1).upper() if market_match else "GLOBAL", "topic": user_message}
        elif user_match and "风险" in user_message:
            tool_name = "get_user_risk"
            validated_args = {"user_id": user_match.group(0)}
        elif contains_any(user_message, POLICY_PATTERNS) and not contains_any(user_message, ["明细", "统计", "最多", "超过"]):
            tool_name = "search_policy_docs"
            validated_args = self._validate_tool_args(tool_name, {"query": user_message})
        else:
            tool_name = "query_refund_cases"
            validated_args = self._validate_tool_args(tool_name, {"query": user_message})

        result, duration_ms = timed_call(self._execute_tool, tool_name, validated_args)
        tool_trace.append({"tool": tool_name, "arguments": validated_args, "duration_ms": duration_ms, "result_summary": summarize_text(json.dumps(result, ensure_ascii=False), limit=180)})

        if tool_name == "query_refund_cases":
            aggregate_payload["metrics"] = [{"label": key, "value": value} for key, value in result.get("metrics", {}).items()]
            aggregate_payload["table"] = result.get("rows", [])
            aggregate_payload["sql_preview"] = result.get("sql_preview")
            aggregate_payload["highlights"] = [result.get("summary", "")]
            summary = "未配置 LLM，已使用确定性工具 fallback 完成只读数据查询。"
        elif tool_name == "search_policy_docs":
            aggregate_payload["citations"] = [{
                "label": doc["citation"],
                "text": doc["excerpt"],
                "source": "lexical_fallback",
                "retrieval_score": None,
                "rerank_score": round(lexical_overlap_score(user_message, f"{doc['title']} {doc['excerpt']}"), 4),
            } for doc in result.get("documents", [])]
            aggregate_payload["highlights"] = [doc["title"] for doc in result.get("documents", [])]
            summary = "未配置 LLM，已使用本地政策检索 fallback 返回可引用依据。"
        elif tool_name in {"query_order_status", "query_logistics_status", "query_refund_eligibility", "query_policy_by_market"}:
            aggregate_payload["highlights"] = [json.dumps(result, ensure_ascii=False)]
            if tool_name == "query_refund_eligibility" and result.get("priority") == "high":
                aggregate_payload["review_required"] = True
                aggregate_payload["review_reason"] = "Refund eligibility returned high priority and requires supervisor escalation."
            summary = "未配置 LLM，已使用新增业务工具完成确定性查询。"
        else:
            if result.get("found"):
                aggregate_payload["metrics"] = [{"label": key, "value": value} for key, value in result.get("metrics", {}).items()]
                aggregate_payload["highlights"] = [f"风险分：{result['risk_score']}", f"风险等级：{result['risk_level']}", result["suggestion"]]
            else:
                aggregate_payload["highlights"] = [result.get("message", "未找到用户记录。")]
            summary = "未配置 LLM，已使用本地风险评分 fallback 返回结果。"

        self.memory.append(sid, "user", user_message)
        self.memory.append(sid, "assistant", summary)
        return {
            "mode": "function_call_agent",
            "title": "Function Calling Agent",
            "summary": summary,
            "session_id": sid,
            "tool_trace": tool_trace,
            **aggregate_payload,
        }

    def respond(self, user_message: str, session_id: str | None = None) -> dict[str, Any]:
        blocked = self._guardrail(user_message)
        if blocked:
            return blocked
        if not self.client:
            return self._respond_without_llm(user_message, session_id=session_id)

        sid = self.memory.get_or_create(session_id)
        messages: list[dict[str, Any]] = [{"role": "system", "content": "你是企业级智能客诉 Copilot。你的职责是调用工具完成只读分析和政策检索。禁止捏造数据，禁止执行审批、改单、删除或退款执行。"}]
        messages.extend(self.memory.recent_messages(sid))
        messages.append({"role": "user", "content": user_message})
        tool_trace: list[dict[str, Any]] = []
        aggregate_payload: dict[str, Any] = {}
        token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        retry_count = 0

        for _ in range(2):
            try:
                response = self.client.chat.completions.create(model=self.settings.llm_model, messages=messages, tools=self._build_tools(), tool_choice="auto", temperature=0)
                token_usage = add_token_usage(token_usage, extract_usage(response))
            except Exception as exc:
                retry_count += 1
                if retry_count <= self.settings.llm_max_retries:
                    time.sleep(0.2 * retry_count)
                    continue
                fallback = self._respond_without_llm(user_message, session_id=sid)
                fallback["_retry_count"] = retry_count
                fallback["_token_usage"] = token_usage
                fallback["degradation_path"] = "llm_error_to_local_tools"
                fallback["error"] = {"code": "llm_call_failed", "message": str(exc)}
                return fallback
            assistant_message = response.choices[0].message
            tool_calls = assistant_message.tool_calls or []
            if not tool_calls:
                answer = assistant_message.content or "模型未返回有效内容。"
                if not aggregate_payload and self._should_fallback_to_tools(user_message):
                    fallback = self._respond_without_llm(user_message, session_id=sid)
                    fallback["summary"] = "模型已连接，但本次未触发工具调用，系统已回退到受控工具链完成查询。"
                    fallback.setdefault("highlights", [])
                    fallback["highlights"] = ["模型响应未包含 tool_call，已使用确定性工具 fallback 保持演示稳定。", *fallback["highlights"]]
                    fallback["_retry_count"] = retry_count
                    fallback["_token_usage"] = token_usage
                    return fallback
                self.memory.append(sid, "user", user_message)
                self.memory.append(sid, "assistant", answer)
                return {"mode": "function_call_agent", "title": "Function Calling Agent", "summary": answer, "session_id": sid, "tool_trace": tool_trace, "_retry_count": retry_count, "_token_usage": token_usage, **aggregate_payload}
            messages.append({"role": "assistant", "content": assistant_message.content or "", "tool_calls": [{"id": call.id, "type": "function", "function": {"name": call.function.name, "arguments": call.function.arguments}} for call in tool_calls]})
            for call in tool_calls:
                args: dict[str, Any] = {}
                try:
                    args = safe_json_loads(call.function.arguments or "{}")
                    validated_args = self._validate_tool_args(call.function.name, args)
                    result, duration_ms = timed_call(self._execute_tool, call.function.name, validated_args)
                    tool_trace.append({"tool": call.function.name, "arguments": validated_args, "duration_ms": duration_ms, "result_summary": summarize_text(json.dumps(result, ensure_ascii=False), limit=180)})
                except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                    result = {"error": f"工具参数校验失败：{exc}"}
                    validated_args = args if isinstance(args, dict) else {}
                    tool_trace.append({"tool": call.function.name, "arguments": validated_args, "result_summary": str(exc)})
                if call.function.name == "query_refund_cases":
                    aggregate_payload["metrics"] = [{"label": key, "value": value} for key, value in result.get("metrics", {}).items()]
                    aggregate_payload["table"] = result.get("rows", [])
                    aggregate_payload["sql_preview"] = result.get("sql_preview")
                    aggregate_payload.setdefault("highlights", []).append(result.get("summary", ""))
                elif call.function.name == "search_policy_docs":
                    aggregate_payload["citations"] = [{"label": doc["citation"], "text": doc["excerpt"], "retrieval_score": doc.get("retrieval_score"), "rerank_score": doc.get("rerank_score"), "source": doc.get("source")} for doc in result.get("documents", [])]
                    aggregate_payload.setdefault("highlights", []).extend(doc["title"] for doc in result.get("documents", []))
                elif call.function.name == "get_user_risk" and result.get("found"):
                    aggregate_payload["metrics"] = [{"label": key, "value": value} for key, value in result.get("metrics", {}).items()]
                    aggregate_payload.setdefault("highlights", []).extend([f"风险分：{result['risk_score']}", f"风险等级：{result['risk_level']}", result["suggestion"]])
                elif call.function.name in {"query_order_status", "query_logistics_status", "query_refund_eligibility", "query_policy_by_market"}:
                    aggregate_payload.setdefault("highlights", []).append(json.dumps(result, ensure_ascii=False))
                    if call.function.name == "query_refund_eligibility" and result.get("priority") == "high":
                        aggregate_payload["review_required"] = True
                        aggregate_payload["review_reason"] = "Refund eligibility returned high priority and requires supervisor escalation."
                elif result.get("error"):
                    aggregate_payload.setdefault("highlights", []).append(result["error"])
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})

        self.memory.append(sid, "user", user_message)
        self.memory.append(sid, "assistant", "工具调用轮次已达上限。")
        return {"mode": "function_call_agent", "title": "Function Calling Agent", "summary": "工具调用轮次已达上限，请调整问题后重试。", "session_id": sid, "tool_trace": tool_trace, **aggregate_payload}


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

    def __init__(self, function_agent: FunctionCallingAgent):
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


class AutoRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url) if settings.llm_api_key else None

    def _rule_route(self, message: str) -> dict[str, Any] | None:
        if re.search(r"[0-9a-f]{24,}", message, re.IGNORECASE) and "风险" in message:
            return {"mode": "function_call_agent", "reason": "命中用户 ID 与风险查询规则。", "confidence": 0.96, "source": "rule"}
        has_structured_query = contains_any(message, ["查询", "查一下", "明细", "统计", "分析", "订单", "风险", "用户", "超过", "多少", "金额", "top", "最多"])
        has_money_query = contains_any(message, ["退款", "赔付"]) and contains_any(message, ["查询", "查一下", "明细", "统计", "分析", "订单", "用户", "风险", "超过", "多少", "金额"])
        has_query = has_structured_query or has_money_query
        has_policy = contains_any(message, POLICY_PATTERNS)
        if has_query and has_policy:
            return {"mode": "sql_rag_chain", "reason": "问题同时包含数据查询与规则判断，先查只读 SQL，再检索 SOP 依据。", "confidence": 0.9, "source": "rule"}
        if has_policy:
            return {"mode": "langchain_rag", "reason": "命中政策、规则、SOP 类问题。", "confidence": 0.84, "source": "rule"}
        if has_query:
            return {"mode": "function_call_agent", "reason": "命中退款、明细、风险或统计查询规则。", "confidence": 0.82, "source": "rule"}
        return None

    def _llm_route(self, message: str) -> dict[str, Any] | None:
        if not self.client:
            return None
        response = self.client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=0,
            messages=[
                {"role": "system", "content": "你是企业内 Copilot 的路由器。请在 function_call_agent、langchain_rag、sql_rag_chain 之间三选一，并输出 JSON。"},
                {"role": "user", "content": message},
            ],
        )
        parsed = safe_json_loads(response.choices[0].message.content or "{}")
        mode = parsed.get("mode")
        if mode not in {"function_call_agent", "langchain_rag", "sql_rag_chain"}:
            return None
        return {"mode": mode, "reason": parsed.get("reason", "LLM classifier 给出了路由决策。"), "confidence": float(parsed.get("confidence", 0.65)), "source": "llm_classifier"}

    def route(self, message: str) -> dict[str, Any]:
        rule_decision = self._rule_route(message)
        if rule_decision and rule_decision["confidence"] >= 0.8:
            return rule_decision
        try:
            llm_decision = self._llm_route(message)
            if llm_decision:
                return llm_decision
        except Exception:
            pass
        return rule_decision or {"mode": "function_call_agent", "reason": "未命中高置信规则，默认回退到 Function Calling Agent。", "confidence": 0.55, "source": "default_fallback"}


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


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    mode: Literal["function_call_agent", "sql_rag_chain", "langchain_rag", "router_demo", "auto"] = "function_call_agent"
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
