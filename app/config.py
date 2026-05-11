from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "Olist"
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"
FRONTEND_ASSETS_DIR = FRONTEND_DIST_DIR / "assets"
KB_DIR = BASE_DIR / "knowledge_base"
VECTOR_DIR = BASE_DIR / "chroma_openai"
SQLITE_DB_PATH = BASE_DIR / "complaint_copilot.sqlite3"
AUDIT_DB_PATH = BASE_DIR / "audit_log.sqlite3"
AUTH_DB_PATH = BASE_DIR / "copilot_auth.sqlite3"

APP_TITLE = "Enterprise Complaint Copilot"
logger = logging.getLogger("complaint_copilot")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(message)s")


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


@dataclass
class Settings:
    llm_api_key: str = ""
    llm_base_url: str | None = None
    llm_model: str = "gpt-4o-mini"
    embedding_api_key: str = ""
    embedding_base_url: str | None = None
    embedding_model: str = "text-embedding-3-small"
    use_langchain_rag: bool = True
    auto_build_vector_store: bool = False
    data_query_backend: Literal["sqlite", "mysql"] = "sqlite"
    jwt_secret: str = "change-me"
    jwt_access_token_minutes: int = 120
    auth_enforced: bool = False
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True
    rate_limit_per_minute: int = 120
    session_ttl_seconds: int = 86400
    cache_ttl_seconds: int = 60
    llm_max_retries: int = 1
    llm_prompt_cost_per_1k: float = 0.0
    llm_completion_cost_per_1k: float = 0.0
    embedding_cost_per_1k: float = 0.0

    def __post_init__(self) -> None:
        self.llm_api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        self.llm_base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        self.llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.embedding_api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        self.embedding_base_url = os.getenv("EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        self.use_langchain_rag = os.getenv("USE_LANGCHAIN_RAG", "true").lower() == "true"
        self.auto_build_vector_store = os.getenv("AUTO_BUILD_VECTOR_STORE", "false").lower() == "true"
        backend = os.getenv("DATA_QUERY_BACKEND", "sqlite").strip().lower()
        self.data_query_backend = "mysql" if backend == "mysql" else "sqlite"
        self.jwt_secret = os.getenv("JWT_SECRET", "dev-change-me")
        self.jwt_access_token_minutes = int(os.getenv("JWT_ACCESS_TOKEN_MINUTES", "120"))
        self.auth_enforced = os.getenv("AUTH_ENFORCED", "false").lower() == "true"
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis_enabled = os.getenv("REDIS_ENABLED", "true").lower() == "true"
        self.rate_limit_per_minute = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
        self.session_ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", "86400"))
        self.cache_ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "60"))
        self.llm_max_retries = int(os.getenv("LLM_MAX_RETRIES", "1"))
        self.llm_prompt_cost_per_1k = float(os.getenv("LLM_PROMPT_COST_PER_1K", "0"))
        self.llm_completion_cost_per_1k = float(os.getenv("LLM_COMPLETION_COST_PER_1K", "0"))
        self.embedding_cost_per_1k = float(os.getenv("EMBEDDING_COST_PER_1K", "0"))
