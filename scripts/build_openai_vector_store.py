from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import chromadb
from langchain_openai import OpenAIEmbeddings


BASE_DIR = Path(__file__).resolve().parents[1]
KB_PATH = BASE_DIR / "knowledge_base" / "policies.json"
VECTOR_DIR = BASE_DIR / "chroma_openai"


def load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the OpenAI-compatible Chroma vector store for policy RAG.")
    parser.add_argument("--rebuild", action="store_true", help="Remove the existing chroma_openai directory before rebuilding.")
    args = parser.parse_args()

    load_dotenv_file(BASE_DIR / ".env")
    api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("请先设置 EMBEDDING_API_KEY 或 OPENAI_API_KEY。")

    if args.rebuild and VECTOR_DIR.exists():
        shutil.rmtree(VECTOR_DIR)

    docs = json.loads(KB_PATH.read_text(encoding="utf-8"))
    texts = [
        f"{doc['title']}\n类别：{doc['category']}\n摘要：{doc['excerpt']}\n规则：{'；'.join(doc['guidance'])}"
        for doc in docs
    ]
    metadatas = [
        {"doc_id": doc["id"], "title": doc["title"], "category": doc["category"], "citation": doc["citation"]}
        for doc in docs
    ]
    ids = [doc["id"] for doc in docs]

    embeddings = OpenAIEmbeddings(
        api_key=api_key,
        base_url=os.getenv("EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
        model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
    )
    vectors = embeddings.embed_documents(texts)

    client = chromadb.PersistentClient(path=str(VECTOR_DIR))
    collection = client.get_or_create_collection(name="policy_docs")
    existing = collection.get()
    if existing.get("ids"):
        collection.delete(ids=existing["ids"])
    collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=vectors)
    print(f"Built vector store at {VECTOR_DIR}")


if __name__ == "__main__":
    main()
