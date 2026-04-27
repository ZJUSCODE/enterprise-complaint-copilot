from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app.utils import SQL_FORBIDDEN_KEYWORDS, summarize_text, validate_readonly_sql


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


@dataclass
class QueryFilters:
    category: str | None = None
    complaint_type: str | None = None
    amount_threshold: float | None = None


def build_tickets_export_frame(analytics: Any) -> pd.DataFrame:
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

    def __init__(self, db_path: Path, analytics: Any):
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
