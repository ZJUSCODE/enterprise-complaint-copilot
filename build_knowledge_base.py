from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

import pandas as pd
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from sqlalchemy import create_engine


BASE_DIR = Path(__file__).resolve().parent


def mysql_engine():
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD")
    host = os.getenv("MYSQL_HOST", "127.0.0.1")
    port = os.getenv("MYSQL_PORT", "3306")
    database = os.getenv("MYSQL_DATABASE", "copilot_db")
    if not password:
        raise RuntimeError("请先设置 MYSQL_PASSWORD 环境变量，再运行知识库构建脚本。")
    encoded_password = urllib.parse.quote_plus(password)
    return create_engine(f"mysql+pymysql://{user}:{encoded_password}@{host}:{port}/{database}?charset=utf8mb4")


print("正在从数据库提取历史客诉案例...")
query = """
SELECT review_comment_message
FROM reviews
WHERE review_score <= 2
  AND review_comment_message IS NOT NULL
LIMIT 500
"""
df_reviews = pd.read_sql(query, con=mysql_engine())

documents = [Document(page_content=text) for text in df_reviews["review_comment_message"]]
documents.extend([
    Document(page_content="针对物流延迟超过7天的用户，需先核验物流节点，再给出安抚和补偿建议。"),
    Document(page_content="针对商品破损的客诉，要求用户上传照片，确认后在24小时内安排补发或退款建议。"),
    Document(page_content="针对高价值用户的差评，建议由主管客服在4小时内介入电话回访。"),
])

print("正在进行文本向量化...")
embeddings = HuggingFaceEmbeddings(model_name=os.getenv("HF_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))

persist_directory = os.getenv("LEGACY_CHROMA_DIR", str(BASE_DIR / "chroma_db"))
print(f"正在构建 ChromaDB 本地索引：{persist_directory}")
Chroma.from_documents(
    documents=documents,
    embedding=embeddings,
    persist_directory=persist_directory,
)

print("RAG 知识库构建完成。")
