from __future__ import annotations

import os
import urllib.parse

import joblib
import pandas as pd
import xgboost as xgb
from imblearn.over_sampling import SMOTE
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sqlalchemy import create_engine


def mysql_engine():
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD")
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = os.getenv("MYSQL_PORT", "3306")
    database = os.getenv("MYSQL_DATABASE", "copilot_db")
    if not password:
        raise RuntimeError("请先设置 MYSQL_PASSWORD 环境变量，再运行训练脚本。")
    encoded_password = urllib.parse.quote_plus(password)
    return create_engine(f"mysql+pymysql://{user}:{encoded_password}@{host}:{port}/{database}?charset=utf8mb4")


query = """
SELECT
    t1.customer_id,
    t2.price,
    t2.freight_value,
    CASE WHEN t3.review_score <= 2 THEN 1 ELSE 0 END AS is_risk
FROM orders t1
JOIN order_items t2 ON t1.order_id = t2.order_id
LEFT JOIN reviews t3 ON t1.order_id = t3.order_id
"""

print("正在从数据库提取业务特征...")
df = pd.read_sql(query, con=mysql_engine())

features = df.groupby("customer_id").agg({
    "price": ["sum", "mean"],
    "freight_value": "mean",
    "is_risk": "max",
}).reset_index()
features.columns = ["customer_id", "total_spend", "avg_price", "avg_freight", "label"]

X = features[["total_spend", "avg_price", "avg_freight"]]
y = features["label"]

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42,
    stratify=y,
)

print("正在对训练集处理样本不平衡...")
smote = SMOTE(random_state=42)
X_train_resampled, y_train_resampled = smote.fit_resample(X_train, y_train)

print("正在训练 XGBoost 风险模型...")
model = xgb.XGBClassifier(
    n_estimators=100,
    max_depth=5,
    learning_rate=0.1,
    random_state=42,
    eval_metric="logloss",
)
model.fit(X_train_resampled, y_train_resampled)

y_pred = model.predict(X_test)
print("\n模型评估报告：")
print(classification_report(y_test, y_pred))

output_path = os.getenv("RISK_MODEL_PATH", "risk_model.pkl")
joblib.dump(model, output_path)
print(f"\n模型已保存到 {output_path}")
