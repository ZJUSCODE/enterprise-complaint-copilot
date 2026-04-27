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
        raise RuntimeError("请先设置 MYSQL_PASSWORD 环境变量，再运行数据补全脚本。")
    encoded_password = urllib.parse.quote_plus(password)
    return create_engine(f"mysql+pymysql://{user}:{encoded_password}@{host}:{port}/{database}?charset=utf8mb4")


engine = mysql_engine()

print("正在读取 order_items CSV 文件...")
df_items = pd.read_csv(BASE_DIR / "olist_order_items_dataset.csv")

print("正在读取 MySQL 中已有订单 ID...")
orders_in_db = pd.read_sql("SELECT order_id FROM orders", con=engine)

sampled_items = df_items[df_items["order_id"].isin(orders_in_db["order_id"])]
sampled_items.to_sql(name="order_items", con=engine, if_exists="replace", index=False)

print("order_items 数据补全完成。")
