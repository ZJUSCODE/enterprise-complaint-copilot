from __future__ import annotations

import json
import re
import time
from typing import Any


SQL_FORBIDDEN_KEYWORDS = {
    "ALTER",
    "ATTACH",
    "CREATE",
    "DELETE",
    "DETACH",
    "DROP",
    "INSERT",
    "PRAGMA",
    "REINDEX",
    "REPLACE",
    "TRUNCATE",
    "UPDATE",
    "VACUUM",
}


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def safe_json_loads(raw_text: str) -> dict[str, Any]:
    payload = (raw_text or "").strip()
    if not payload:
        return {}
    try:
        loaded = json.loads(payload)
    except json.JSONDecodeError:
        fenced = re.sub(r"^```(?:json)?|```$", "", payload, flags=re.MULTILINE).strip()
        loaded = json.loads(fenced)
    if not isinstance(loaded, dict):
        raise ValueError("tool arguments must be a JSON object")
    return loaded


def summarize_text(text: str, limit: int = 110) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    return clean[:limit] + ("..." if len(clean) > limit else "")


def _strip_sql_literals_and_comments(sql: str) -> str:
    sanitized: list[str] = []
    i = 0
    in_single_quote = False
    in_double_quote = False
    length = len(sql)
    while i < length:
        char = sql[i]
        next_char = sql[i + 1] if i + 1 < length else ""

        if in_single_quote:
            sanitized.append(" ")
            if char == "'" and next_char == "'":
                sanitized.append(" ")
                i += 2
                continue
            if char == "'":
                in_single_quote = False
            i += 1
            continue

        if in_double_quote:
            sanitized.append(" ")
            if char == '"' and next_char == '"':
                sanitized.append(" ")
                i += 2
                continue
            if char == '"':
                in_double_quote = False
            i += 1
            continue

        if char == "-" and next_char == "-":
            sanitized.append(" ")
            i += 2
            while i < length and sql[i] not in "\r\n":
                i += 1
            continue

        if char == "/" and next_char == "*":
            sanitized.append(" ")
            i += 2
            while i + 1 < length and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i += 2
            continue

        if char == "'":
            in_single_quote = True
            sanitized.append(" ")
            i += 1
            continue

        if char == '"':
            in_double_quote = True
            sanitized.append(" ")
            i += 1
            continue

        sanitized.append(char)
        i += 1

    if in_single_quote or in_double_quote:
        raise ValueError("SQL 字符串字面量未闭合。")
    return "".join(sanitized)


def validate_readonly_sql(sql: str) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("SQL 不能为空。")

    sanitized = _strip_sql_literals_and_comments(sql)
    statements = [statement.strip() for statement in sanitized.split(";") if statement.strip()]
    if len(statements) != 1:
        raise ValueError("只允许执行单条只读 SQL。")

    statement = re.sub(r"\s+", " ", statements[0]).strip()
    upper_statement = statement.upper()
    if not upper_statement.startswith(("SELECT ", "WITH ")):
        raise ValueError("只允许 SELECT/WITH 只读查询。")

    tokens = set(re.findall(r"\b[A-Z_]+\b", upper_statement))
    forbidden = sorted(tokens & SQL_FORBIDDEN_KEYWORDS)
    if forbidden:
        raise ValueError(f"只读 SQL 禁止包含写操作关键字：{', '.join(forbidden)}。")
    if re.search(r"\bSELECT\b.+\bINTO\b", upper_statement):
        raise ValueError("只读 SQL 禁止 SELECT INTO。")
    return sql


def lexical_overlap_score(query: str, text: str) -> float:
    query_tokens = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", query.lower()))
    text_tokens = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", text.lower()))
    if not query_tokens or not text_tokens:
        return 0.0
    return len(query_tokens & text_tokens) / max(len(query_tokens), 1)


def extract_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if not usage:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    total_tokens = int(getattr(usage, "total_tokens", prompt_tokens + completion_tokens) or 0)
    return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": total_tokens}


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    ascii_words = re.findall(r"[A-Za-z0-9_]+", text)
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    other_chars = max(len(text) - sum(len(word) for word in ascii_words) - len(cjk_chars), 0)
    return max(1, len(ascii_words) + len(cjk_chars) + other_chars // 4)


def extract_langchain_usage(message: Any, prompt: str = "", answer: str = "") -> dict[str, int]:
    usage = getattr(message, "usage_metadata", None) or {}
    if usage:
        input_tokens = int(usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or usage.get("completion_tokens", 0) or 0)
        total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
        return {"prompt_tokens": input_tokens, "completion_tokens": output_tokens, "total_tokens": total_tokens}

    response_metadata = getattr(message, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage") or response_metadata.get("usage") or {}
    if token_usage:
        prompt_tokens = int(token_usage.get("prompt_tokens", 0) or token_usage.get("input_tokens", 0) or 0)
        completion_tokens = int(token_usage.get("completion_tokens", 0) or token_usage.get("output_tokens", 0) or 0)
        total_tokens = int(token_usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)
        return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": total_tokens}

    prompt_tokens = estimate_text_tokens(prompt)
    completion_tokens = estimate_text_tokens(answer)
    return {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens}


def add_token_usage(current: dict[str, int], delta: dict[str, int]) -> dict[str, int]:
    keys = set(current) | set(delta) | {"prompt_tokens", "completion_tokens", "total_tokens"}
    merged = {key: int(current.get(key, 0)) + int(delta.get(key, 0)) for key in keys}
    if not merged.get("total_tokens"):
        merged["total_tokens"] = int(merged.get("embedding_tokens", 0)) + int(merged.get("prompt_tokens", 0)) + int(merged.get("completion_tokens", 0))
    return merged


def estimate_cost(settings: Any, usage: dict[str, int]) -> float:
    prompt_cost = (usage.get("prompt_tokens", 0) / 1000.0) * settings.llm_prompt_cost_per_1k
    completion_cost = (usage.get("completion_tokens", 0) / 1000.0) * settings.llm_completion_cost_per_1k
    return round(prompt_cost + completion_cost, 8)


def estimate_cost_breakdown(settings: Any, usage: dict[str, int]) -> dict[str, float]:
    embedding_cost = (usage.get("embedding_tokens", 0) / 1000.0) * settings.embedding_cost_per_1k
    prompt_cost = (usage.get("prompt_tokens", 0) / 1000.0) * settings.llm_prompt_cost_per_1k
    completion_cost = (usage.get("completion_tokens", 0) / 1000.0) * settings.llm_completion_cost_per_1k
    total = embedding_cost + prompt_cost + completion_cost
    return {
        "embedding_cost_usd": round(embedding_cost, 8),
        "prompt_cost_usd": round(prompt_cost, 8),
        "completion_cost_usd": round(completion_cost, 8),
        "total_cost_usd": round(total, 8),
    }


def timed_call(fn, *args, **kwargs):
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    return result, duration_ms
