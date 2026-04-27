from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import Float, Integer, String, Text, create_engine

from app.runtime import DATA_DIR, BASE_DIR, LocalAnalyticsEngine, build_tickets_export_frame, load_dotenv_file


def mysql_engine():
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD")
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = os.getenv("MYSQL_PORT", "3306")
    database = os.getenv("MYSQL_DATABASE", "copilot_db")
    if not password or password == "your_mysql_password":
        raise RuntimeError("请先设置 MYSQL_PASSWORD，用有写权限的账号导入 tickets 表。")
    encoded_password = urllib.parse.quote_plus(password)
    return create_engine(f"mysql+pymysql://{user}:{encoded_password}@{host}:{port}/{database}?charset=utf8mb4")


MYSQL_TICKETS_DTYPE = {
    "order_id": String(64),
    "user_id": String(64),
    "category": String(32),
    "complaint_type": String(32),
    "compensation_amount": Float,
    "pay_amount": Float,
    "created_at": String(32),
    "comment": Text,
    "is_bad_review": Integer,
    "ticket_status": Integer,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and sync the Copilot tickets wide table into MySQL.")
    parser.add_argument("--if-exists", choices=("replace", "append", "fail"), default="replace")
    args = parser.parse_args()

    load_dotenv_file(BASE_DIR / ".env")
    analytics = LocalAnalyticsEngine(DATA_DIR)
    tickets = build_tickets_export_frame(analytics)
    engine = mysql_engine()
    print(f"正在写入 MySQL tickets 表，行数：{len(tickets)}，策略：{args.if_exists}")
    tickets.to_sql(name="tickets", con=engine, if_exists=args.if_exists, index=False, chunksize=2000, dtype=MYSQL_TICKETS_DTYPE)
    with engine.begin() as conn:
        for sql in (
            "CREATE INDEX idx_tickets_readonly ON tickets(is_bad_review, ticket_status, complaint_type, category, compensation_amount)",
            "CREATE INDEX idx_tickets_user ON tickets(user_id)",
        ):
            try:
                conn.exec_driver_sql(sql)
            except Exception as exc:
                if "Duplicate" not in str(exc) and "already exists" not in str(exc):
                    raise
    print("MySQL tickets 表同步完成。建议应用查询使用只有 SELECT 权限的 MYSQL_READONLY_USER。")


if __name__ == "__main__":
    main()
