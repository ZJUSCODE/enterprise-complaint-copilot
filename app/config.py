from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "demo_data"
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
    demo_mode: bool = False
    auth_enforced: bool = True
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = True
    rate_limit_per_minute: int = 120
    session_ttl_seconds: int = 86400
    cache_ttl_seconds: int = 60
    llm_max_retries: int = 1
    llm_prompt_cost_per_1k: float = 0.0
    llm_completion_cost_per_1k: float = 0.0
    embedding_cost_per_1k: float = 0.0
    # 外部检索后端（WeKnora）：RETRIEVAL_BACKEND=weknora 时启用
    retrieval_backend: str = "local"
    weknora_base_url: str = ""
    weknora_api_key: str = ""
    weknora_kb_id: str = ""
    # 混合检索调参（hybrid_bm25）：调优后默认值（2026-08-18，88.9% vs 原 55.6%）
    # 实验结论：BM25 候选 9 + POL 政策锚点加权 1.5 + BM25 融合权重 2.0 达到评测上限
    hybrid_vector_candidates: int = 6
    hybrid_bm25_candidates: int = 9
    hybrid_bm25_weight: float = 2.0
    hybrid_rrf_k: int = 60
    hybrid_vector_threshold: float = 0.0
    hybrid_policy_weight: float = 1.5

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
        self.demo_mode = os.getenv("DEMO_MODE", "false").strip().lower() == "true"
        self.auth_enforced = not self.demo_mode
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis_enabled = os.getenv("REDIS_ENABLED", "true").lower() == "true"
        self.rate_limit_per_minute = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
        self.session_ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", "86400"))
        self.cache_ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "60"))
        self.llm_max_retries = int(os.getenv("LLM_MAX_RETRIES", "1"))
        self.llm_prompt_cost_per_1k = float(os.getenv("LLM_PROMPT_COST_PER_1K", "0"))
        self.llm_completion_cost_per_1k = float(os.getenv("LLM_COMPLETION_COST_PER_1K", "0"))
        self.embedding_cost_per_1k = float(os.getenv("EMBEDDING_COST_PER_1K", "0"))
        self.retrieval_backend = os.getenv("RETRIEVAL_BACKEND", "local").strip().lower()
        self.weknora_base_url = os.getenv("WEKNORA_BASE_URL", "").strip().rstrip("/")
        self.weknora_api_key = os.getenv("WEKNORA_API_KEY", "").strip()
        self.weknora_kb_id = os.getenv("WEKNORA_KB_ID", "").strip()
        # 混合检索调参（环境变量可覆盖，默认值已固化为调优结果）
        self.hybrid_vector_candidates = int(os.getenv("HYBRID_VECTOR_CANDIDATES", "6"))
        self.hybrid_bm25_candidates = int(os.getenv("HYBRID_BM25_CANDIDATES", "9"))
        self.hybrid_bm25_weight = float(os.getenv("HYBRID_BM25_WEIGHT", "2.0"))
        self.hybrid_rrf_k = int(os.getenv("HYBRID_RRF_K", "60"))
        self.hybrid_vector_threshold = float(os.getenv("HYBRID_VECTOR_THRESHOLD", "0.0"))
        self.hybrid_policy_weight = float(os.getenv("HYBRID_POLICY_WEIGHT", "1.5"))
