from __future__ import annotations

import argparse
import csv
import hashlib
import math
import os
import random
import shutil
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.analytics import LocalAnalyticsEngine
from app.audit_stores import AuditLogStore, FeedbackEventStore, HumanReviewQueue
from app.config import AUDIT_DB_PATH, DATA_DIR, SQLITE_DB_PATH
from app.ticket_store import ReadOnlySQLiteStore


CATEGORY_CONFIG = {
    "electronics": {"weight": 0.24, "price": (220, 1800), "anomaly_rate": 0.14},
    "food_drinks": {"weight": 0.18, "price": (25, 260), "anomaly_rate": 0.11},
    "fashion_shoes": {"weight": 0.22, "price": (60, 620), "anomaly_rate": 0.10},
    "beauty_health": {"weight": 0.20, "price": (45, 780), "anomaly_rate": 0.09},
    "housewares": {"weight": 0.16, "price": (80, 1200), "anomaly_rate": 0.08},
}

COMPLAINTS = {
    "质量问题": "商品质量问题，开箱后无法正常使用，需要核验照片和故障描述。",
    "物流延误": "物流延误，超过承诺时间仍未送达，请核查配送节点。",
    "包装破损": "包装破损，外箱挤压导致商品受损，已保留开箱照片。",
    "仅退款": "申请仅退款，商品与页面描述不符，等待客服复核。",
}

NORMAL_COMMENTS = [
    "商品符合预期，配送正常。",
    "包装完整，使用体验良好。",
    "客服回复及时，问题已解决。",
    "收到商品，整体满意。",
]


def stable_id(prefix: str, index: int) -> str:
    return hashlib.sha256(f"{prefix}-{index:06d}".encode()).hexdigest()[:32]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate_data(target_dir: Path, end_date: date, days: int, seed: int) -> dict[str, int | str]:
    rng = random.Random(seed)
    target_dir.mkdir(parents=True, exist_ok=True)
    categories = list(CATEGORY_CONFIG)
    category_weights = [CATEGORY_CONFIG[item]["weight"] for item in categories]

    products = []
    products_by_category: dict[str, list[str]] = {item: [] for item in categories}
    for product_index in range(80):
        category = categories[product_index % len(categories)]
        product_id = stable_id("product", product_index)
        products_by_category[category].append(product_id)
        products.append({
            "product_id": product_id,
            "product_category_name": category,
            "product_name_lenght": rng.randint(24, 68),
            "product_description_lenght": rng.randint(120, 980),
            "product_photos_qty": rng.randint(1, 6),
            "product_weight_g": rng.randint(120, 5200),
            "product_length_cm": rng.randint(12, 65),
            "product_height_cm": rng.randint(5, 42),
            "product_width_cm": rng.randint(10, 55),
        })

    users = [stable_id("user", index) for index in range(1, 4201)]
    orders: list[dict] = []
    items: list[dict] = []
    reviews: list[dict] = []
    anomaly_count = 0
    order_index = 0
    start_date = end_date - timedelta(days=days - 1)

    for day_offset in range(days):
        current_day = start_date + timedelta(days=day_offset)
        weekday_effect = 15 if current_day.weekday() < 5 else -8
        seasonal_effect = int(13 * math.sin(day_offset / 5.5) + 8 * math.sin(day_offset / 13.0))
        daily_orders = max(70, 118 + weekday_effect + seasonal_effect + rng.randint(-8, 8))

        for _ in range(daily_orders):
            order_index += 1
            order_id = stable_id("order", order_index)
            user_id = rng.choice(users)
            category = rng.choices(categories, weights=category_weights, k=1)[0]
            config = CATEGORY_CONFIG[category]
            purchase_time = datetime.combine(current_day, datetime.min.time()) + timedelta(
                hours=rng.randint(8, 22), minutes=rng.randint(0, 59), seconds=rng.randint(0, 59)
            )
            approved_time = purchase_time + timedelta(minutes=rng.randint(5, 120))
            estimated_days = rng.randint(3, 6)
            anomaly_probability = float(config["anomaly_rate"]) + 0.012 * math.sin(day_offset / 4.0)
            is_anomaly = rng.random() < anomaly_probability
            complaint_type = rng.choices(
                list(COMPLAINTS),
                weights=[0.44, 0.30, 0.16, 0.10],
                k=1,
            )[0] if is_anomaly else None
            delivery_days = estimated_days + rng.randint(-2, 1)
            if complaint_type == "物流延误":
                delivery_days = estimated_days + rng.randint(2, 5)
            delivered_time = purchase_time + timedelta(days=max(1, delivery_days), hours=rng.randint(1, 8))
            estimated_time = purchase_time + timedelta(days=estimated_days)
            price_low, price_high = config["price"]
            price = round(rng.triangular(price_low, price_high, price_low * 1.35), 2)
            freight = round(max(6.0, price * rng.uniform(0.035, 0.09)), 2)
            product_id = rng.choice(products_by_category[category])

            orders.append({
                "order_id": order_id,
                "customer_id": user_id,
                "order_status": "delivered",
                "order_purchase_timestamp": purchase_time.isoformat(sep=" "),
                "order_approved_at": approved_time.isoformat(sep=" "),
                "order_delivered_carrier_date": (approved_time + timedelta(hours=rng.randint(8, 36))).isoformat(sep=" "),
                "order_delivered_customer_date": delivered_time.isoformat(sep=" "),
                "order_estimated_delivery_date": estimated_time.isoformat(sep=" "),
            })
            items.append({
                "order_id": order_id,
                "order_item_id": 1,
                "product_id": product_id,
                "seller_id": stable_id("seller", rng.randint(1, 120)),
                "shipping_limit_date": (approved_time + timedelta(days=2)).isoformat(sep=" "),
                "price": price,
                "freight_value": freight,
            })

            if is_anomaly:
                anomaly_count += 1
                review_score = rng.choices([1, 2], weights=[0.42, 0.58], k=1)[0]
                comment = COMPLAINTS[complaint_type]
                title = complaint_type
            else:
                review_score = rng.choices([3, 4, 5], weights=[0.08, 0.38, 0.54], k=1)[0]
                comment = rng.choice(NORMAL_COMMENTS)
                title = "评价"
            review_time = delivered_time + timedelta(days=rng.randint(0, 3))
            reviews.append({
                "review_id": stable_id("review", order_index),
                "order_id": order_id,
                "review_score": review_score,
                "review_comment_title": title,
                "review_comment_message": comment,
                "review_creation_date": review_time.date().isoformat(),
                "review_answer_timestamp": (review_time + timedelta(hours=rng.randint(1, 18))).isoformat(sep=" "),
            })

    write_csv(target_dir / "olist_orders_dataset.csv", list(orders[0]), orders)
    write_csv(target_dir / "olist_order_items_dataset.csv", list(items[0]), items)
    write_csv(target_dir / "olist_order_reviews_dataset.csv", list(reviews[0]), reviews)
    write_csv(target_dir / "olist_products_dataset.csv", list(products[0]), products)
    return {
        "orders": len(orders),
        "users": len({item["customer_id"] for item in orders}),
        "anomalies": anomaly_count,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }


def build_databases(data_dir: Path, sqlite_path: Path, audit_path: Path | None = None) -> None:
    analytics = LocalAnalyticsEngine(data_dir)
    ReadOnlySQLiteStore(sqlite_path, analytics)
    if audit_path is not None:
        AuditLogStore(audit_path)
        HumanReviewQueue(audit_path)
        FeedbackEventStore(audit_path)


def validate_staged_reset(data_dir: Path, sqlite_path: Path, summary: dict[str, int | str]) -> None:
    required_csvs = {
        "olist_orders_dataset.csv", "olist_order_items_dataset.csv",
        "olist_order_reviews_dataset.csv", "olist_products_dataset.csv",
    }
    if {path.name for path in data_dir.glob("*.csv")} != required_csvs:
        raise RuntimeError("staged demo data is incomplete")
    with sqlite3.connect(sqlite_path) as conn:
        row_count = int(conn.execute("SELECT COUNT(DISTINCT order_id) FROM tickets").fetchone()[0])
        date_range = conn.execute("SELECT MIN(created_at), MAX(created_at) FROM tickets").fetchone()
    if row_count != int(summary["orders"]):
        raise RuntimeError(f"staged SQLite order count mismatch: {row_count} != {summary['orders']}")
    if tuple(date_range) != (summary["start_date"], summary["end_date"]):
        raise RuntimeError(f"staged SQLite date range mismatch: {date_range}")


def swap_staged_reset(staged_data: Path, staged_sqlite: Path, staged_audit: Path | None, work_dir: Path) -> None:
    backup_data = work_dir / "backup_demo_data"
    backup_sqlite = work_dir / "backup_complaint_copilot.sqlite3"
    backup_audit = work_dir / "backup_audit_log.sqlite3"
    data_backed_up = sqlite_backed_up = audit_backed_up = False
    data_installed = sqlite_installed = audit_installed = False
    try:
        if DATA_DIR.exists():
            os.replace(DATA_DIR, backup_data)
            data_backed_up = True
        os.replace(staged_data, DATA_DIR)
        data_installed = True
        if SQLITE_DB_PATH.exists():
            os.replace(SQLITE_DB_PATH, backup_sqlite)
            sqlite_backed_up = True
        os.replace(staged_sqlite, SQLITE_DB_PATH)
        sqlite_installed = True
        if staged_audit is not None:
            if AUDIT_DB_PATH.exists():
                os.replace(AUDIT_DB_PATH, backup_audit)
                audit_backed_up = True
            os.replace(staged_audit, AUDIT_DB_PATH)
            audit_installed = True
    except Exception:
        if audit_installed:
            AUDIT_DB_PATH.unlink(missing_ok=True)
        if audit_backed_up:
            os.replace(backup_audit, AUDIT_DB_PATH)
        if sqlite_installed:
            SQLITE_DB_PATH.unlink(missing_ok=True)
        if sqlite_backed_up:
            os.replace(backup_sqlite, SQLITE_DB_PATH)
        if data_installed:
            shutil.rmtree(DATA_DIR, ignore_errors=True)
        if data_backed_up:
            os.replace(backup_data, DATA_DIR)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset Complaint Copilot with deterministic synthetic demo data.")
    parser.add_argument("--confirm-reset-demo-data", action="store_true")
    parser.add_argument("--clear-audit", action="store_true", help="Also clear audit, review, and feedback history.")
    parser.add_argument("--end-date", default="2026-07-28")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--seed", type=int, default=20260729)
    args = parser.parse_args()
    if not args.confirm_reset_demo_data:
        parser.error("reset refused: pass --confirm-reset-demo-data after stopping the app server")
    if os.getenv("DATA_QUERY_BACKEND", "sqlite").strip().lower() == "mysql":
        parser.error("reset refused: DATA_QUERY_BACKEND=mysql is not supported")
    if args.days < 30:
        parser.error("--days must be at least 30 so the dashboard has a valid 30-day trend")
    end_date = date.fromisoformat(args.end_date)

    with tempfile.TemporaryDirectory(prefix=".complaint-copilot-reset-", dir=ROOT) as temp_dir:
        temp_path = Path(temp_dir)
        staged_data = temp_path / "demo_data"
        staged_sqlite = temp_path / "complaint_copilot.sqlite3"
        staged_audit = temp_path / "audit_log.sqlite3" if args.clear_audit else None
        summary = generate_data(staged_data, end_date=end_date, days=args.days, seed=args.seed)
        build_databases(staged_data, staged_sqlite, staged_audit)
        validate_staged_reset(staged_data, staged_sqlite, summary)
        swap_staged_reset(staged_data, staged_sqlite, staged_audit, temp_path)
    print(
        f"reset complete: {summary['orders']} orders, {summary['users']} users, "
        f"{summary['anomalies']} anomalies, {summary['start_date']} to {summary['end_date']}; "
        f"audit={'cleared' if args.clear_audit else 'preserved'}; restart the app server"
    )


if __name__ == "__main__":
    main()
