"""Settings, read from environment variables and from a local .env file when there is one."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_SUGGESTIONS = (
    "How many vacation days do I get in my first year?",
    "What should I do if my laptop is stolen?",
    "Can I work from another country for a few weeks?",
    "Which tools does Northwind connect to?",
)


def load_dotenv(path: Path) -> None:
    """Read KEY=value lines into os.environ. Variables that are already set win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            comment = value.find(" #")
            if comment != -1:
                value = value[:comment].rstrip()
        if key:
            os.environ.setdefault(key, value)


def _bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def _int(env: Mapping[str, str], name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(env.get(name, "").strip())
    except ValueError:
        return default
    return max(low, min(high, value))


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    try:
        return float(env.get(name, "").strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    company_name: str
    assistant_name: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout: float
    query_rewrite: bool
    embeddings: str
    embedding_model: str
    embedding_base_url: str
    embedding_api_key: str
    embedding_cache_dir: Path
    semantic_min_score: float
    chunk_size: int
    chunk_overlap: int
    top_k: int
    max_upload_mb: int
    max_pages: int
    admin_token: str
    load_sample_docs: bool
    suggested_questions: tuple[str, ...]

    @property
    def llm_enabled(self) -> bool:
        if not self.llm_base_url or not self.llm_model:
            return False
        if self.llm_api_key:
            return True
        # Local servers such as Ollama or LM Studio don't need a key, OpenAI does.
        return "api.openai.com" not in self.llm_base_url

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "knowledge.db"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        data_dir = Path(env.get("DATA_DIR", "").strip() or BASE_DIR / "data")
        llm_base_url = env.get("LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
        llm_api_key = env.get("LLM_API_KEY", "").strip()

        embeddings = env.get("EMBEDDINGS", "local").strip().lower() or "local"
        if embeddings not in {"local", "api", "off"}:
            embeddings = "local"
        default_embedding_model = (
            "text-embedding-3-small" if embeddings == "api" else "BAAI/bge-small-en-v1.5"
        )
        cache_dir = env.get("EMBEDDING_CACHE_DIR", "").strip()

        suggestions = tuple(
            q.strip() for q in env.get("SUGGESTED_QUESTIONS", "").split("|") if q.strip()
        ) or DEFAULT_SUGGESTIONS

        chunk_size = _int(env, "CHUNK_SIZE", 900, 300, 4000)
        return cls(
            data_dir=data_dir,
            company_name=env.get("COMPANY_NAME", "").strip() or "Northwind Analytics",
            assistant_name=env.get("ASSISTANT_NAME", "").strip() or "Knowledge Base Assistant",
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=env.get("LLM_MODEL", "").strip() or "gpt-4.1-mini",
            llm_timeout=_float(env, "LLM_TIMEOUT", 60.0),
            query_rewrite=_bool(env, "QUERY_REWRITE", True),
            embeddings=embeddings,
            embedding_model=env.get("EMBEDDING_MODEL", "").strip() or default_embedding_model,
            embedding_base_url=(env.get("EMBEDDING_BASE_URL", "").strip() or llm_base_url).rstrip("/"),
            embedding_api_key=env.get("EMBEDDING_API_KEY", "").strip() or llm_api_key,
            embedding_cache_dir=Path(cache_dir) if cache_dir else data_dir / "models",
            semantic_min_score=_float(env, "SEMANTIC_MIN_SCORE", 0.25),
            chunk_size=chunk_size,
            chunk_overlap=_int(env, "CHUNK_OVERLAP", 150, 0, chunk_size // 2),
            top_k=_int(env, "TOP_K", 6, 1, 20),
            max_upload_mb=_int(env, "MAX_UPLOAD_MB", 25, 1, 500),
            max_pages=_int(env, "MAX_PAGES", 500, 1, 5000),
            admin_token=env.get("ADMIN_TOKEN", "").strip(),
            load_sample_docs=_bool(env, "LOAD_SAMPLE_DOCS", True),
            suggested_questions=suggestions,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")
    return Settings.from_env(os.environ)
