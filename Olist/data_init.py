from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine


BASE_DIR = Path(__file__).resolve().parent


def mysql_engine():
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD")
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = os.getenv("MYSQL_PORT", "3306")
    database = os.getenv("MYSQL_DATABASE", "copilot_db")
    if not password:
        raise RuntimeError("请先设置 MYSQL_PASSWORD 环境变量，再运行数据导入脚本。")
    encoded_password = urllib.parse.quote_plus(password)
    return create_engine(f"mysql+pymysql://{user}:{encoded_password}@{host}:{port}/{database}?charset=utf8mb4")


orders_file = BASE_DIR / "olist_orders_dataset.csv"
reviews_file = BASE_DIR / "olist_order_reviews_dataset.csv"

print("正在读取 Olist CSV 文件...")
df_orders = pd.read_csv(orders_file)
df_reviews = pd.read_csv(reviews_file)
print(f"原始数据量：订单 {len(df_orders)} 条，评论 {len(df_reviews)} 条。")

sample_size = int(os.getenv("OLIST_SAMPLE_SIZE", "5000"))
sampled_orders = df_orders.sample(n=min(sample_size, len(df_orders)), random_state=42)
sampled_reviews = df_reviews[df_reviews["order_id"].isin(sampled_orders["order_id"])]

engine = mysql_engine()
print("正在写入 MySQL 表 orders...")
sampled_orders.to_sql(name="orders", con=engine, if_exists="replace", index=False)

print("正在写入 MySQL 表 reviews...")
sampled_reviews.to_sql(name="reviews", con=engine, if_exists="replace", index=False)

print("Olist 样本数据导入完成。")
