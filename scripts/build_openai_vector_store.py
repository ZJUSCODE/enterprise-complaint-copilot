from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import chromadb
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


BASE_DIR = Path(__file__).resolve().parents[1]
KB_PATH = BASE_DIR / "knowledge_base" / "policies.json"
KB_DIR = BASE_DIR / "knowledge_base"
VECTOR_DIR = BASE_DIR / "chroma_openai"
VECTOR_MANIFEST = "kb_manifest.json"


def knowledge_base_hash(kb_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted([kb_dir / "policies.json", *kb_dir.glob("**/*.md")]):
        if not path.exists() or path.name.lower().startswith("readme"):
            continue
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


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


def _extract_section_title(chunk_text: str) -> str:
    """Find the most recent ## heading in or before the chunk text."""
    headings = re.findall(r"^##\s+(.+)$", chunk_text, re.MULTILINE)
    return headings[-1].strip() if headings else ""


def _infer_category(path: Path, filename: str, first_heading: str) -> str:
    """Infer document category from filename, path or first heading."""
    name_lower = filename.lower()
    rel = path.as_posix().lower()
    rules = [
        ("3c", "3C数码"), ("digital", "3C数码"), ("数码", "3C数码"),
        ("fresh", "生鲜"), ("生鲜", "生鲜"),
        ("food", "食品"), ("食品", "食品"),
        ("apparel", "服饰"), ("服饰", "服饰"),
        ("home", "家居"), ("furnishing", "家居"), ("家居", "家居"),
        ("beauty", "美妆"), ("cosmetic", "美妆"), ("美妆", "美妆"),
        ("logistics", "物流"), ("物流", "物流"),
        ("refund", "退款"), ("退款", "退款"),
    ]
    for keyword, category in rules:
        if keyword in name_lower or keyword in rel:
            return category
    if "售后" in first_heading:
        return "售后"
    if "物流" in first_heading:
        return "物流"
    return "通用"


def load_markdown_docs(kb_dir: Path) -> tuple[list[str], list[dict], list[str]]:
    """Load *.md files from kb_dir, split into chunks, return (texts, metadatas, ids)."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=300,
        chunk_overlap=50,
        separators=["\n## ", "\n\n", "\n", "。", "；", " "],
        keep_separator=True,
    )
    all_texts: list[str] = []
    all_metadatas: list[dict] = []
    all_ids: list[str] = []
    chunk_counter = 0

    for md_file in sorted(kb_dir.glob("**/*.md")):
        if md_file.name.lower().startswith("readme"):
            continue
        content = md_file.read_text(encoding="utf-8")
        chunks = splitter.split_text(content)
        category = _infer_category(md_file.relative_to(kb_dir), md_file.name, chunks[0] if chunks else "")
        # Extract first heading for citation
        first_heading_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        doc_title = first_heading_match.group(1).strip() if first_heading_match else md_file.stem

        for chunk in chunks:
            chunk_counter += 1
            section_title = _extract_section_title(chunk)
            chunk_id = f"{md_file.stem}_chunk_{chunk_counter:03d}"
            title = section_title or doc_title
            citation = f"{md_file.name} > {section_title}" if section_title else md_file.name
            all_texts.append(chunk)
            all_metadatas.append({
                "doc_id": chunk_id,
                "title": title,
                "category": category,
                "citation": citation,
                "source_file": md_file.name,
                "section_title": section_title,
            })
            all_ids.append(chunk_id)

    return all_texts, all_metadatas, all_ids


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

    # --- Part 1: policies.json (structured, no chunking) ---
    docs = json.loads(KB_PATH.read_text(encoding="utf-8"))
    policy_texts = [
        f"{doc['title']}\n类别：{doc['category']}\n摘要：{doc['excerpt']}\n规则：{'；'.join(doc['guidance'])}"
        for doc in docs
    ]
    policy_metadatas = [
        {"doc_id": doc["id"], "title": doc["title"], "category": doc["category"], "citation": doc["citation"]}
        for doc in docs
    ]
    policy_ids = [doc["id"] for doc in docs]

    # --- Part 2: markdown SOP docs (chunked) ---
    md_texts, md_metadatas, md_ids = load_markdown_docs(KB_DIR)

    # --- Combine ---
    all_texts = policy_texts + md_texts
    all_metadatas = policy_metadatas + md_metadatas
    all_ids = policy_ids + md_ids

    print(f"Embedding {len(policy_texts)} policy docs + {len(md_texts)} markdown chunks = {len(all_texts)} total")

    embeddings = OpenAIEmbeddings(
        api_key=api_key,
        base_url=os.getenv("EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
        model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
    )
    vectors = embeddings.embed_documents(all_texts)

    client = chromadb.PersistentClient(path=str(VECTOR_DIR))
    collection = client.get_or_create_collection(name="policy_docs")
    existing = collection.get()
    if existing.get("ids"):
        collection.delete(ids=existing["ids"])
    collection.add(ids=all_ids, documents=all_texts, metadatas=all_metadatas, embeddings=vectors)
    (VECTOR_DIR / VECTOR_MANIFEST).write_text(
        json.dumps({"knowledge_base_hash": knowledge_base_hash(KB_DIR)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Built vector store at {VECTOR_DIR} ({len(all_texts)} vectors)")


if __name__ == "__main__":
    main()
