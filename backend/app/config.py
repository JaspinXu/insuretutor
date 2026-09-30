"""Application settings, loaded from environment variables (and `.env` in dev).

Every tunable lives here so that behaviour can be changed from `.env` /
`docker-compose.yml` without touching code. Secrets are never logged.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MODELS = {
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-opus-5-5",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM -------------------------------------------------------------
    # "auto" picks anthropic if ANTHROPIC_API_KEY is set, else openai if
    # OPENAI_API_KEY is set, else the offline (extractive, no-LLM) mode.
    llm_provider: Literal["auto", "openai", "anthropic", "offline"] = "auto"
    llm_model: str | None = None
    # Model used for the routing / query-rewriting call. Defaults to llm_model.
    router_model: str | None = None
    llm_timeout_s: float = 60.0

    # OpenAI or any OpenAI-compatible endpoint (DeepSeek, Qwen/DashScope, Ollama...)
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_temperature: float = 0.1
    openai_max_tokens: int = 1500

    anthropic_api_key: str | None = None
    anthropic_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    anthropic_router_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    # Server-side refusal fallback (beta). Disable if your account/SDK rejects it.
    anthropic_refusal_fallback: bool = True

    # --- Retrieval ---------------------------------------------------------
    embedding_backend: Literal["local", "openai", "none"] = "local"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_api_key: str | None = None  # defaults to OPENAI_API_KEY
    embedding_base_url: str | None = None  # defaults to OPENAI_BASE_URL
    top_k: int = Field(6, ge=1, le=20)

    # --- Paths -------------------------------------------------------------
    data_dir: Path = REPO_ROOT / "data"
    var_dir: Path = REPO_ROOT / "var"
    static_dir: Path | None = None  # built frontend; served at "/" when set

    # --- Guardrails / limits ---------------------------------------------
    max_input_chars: int = 2000
    history_turns: int = 6
    rate_limit_per_minute: int = 30

    log_level: str = "INFO"

    @property
    def provider(self) -> Literal["openai", "anthropic", "offline"]:
        if self.llm_provider != "auto":
            return self.llm_provider
        if self.anthropic_api_key:
            return "anthropic"
        if self.openai_api_key:
            return "openai"
        return "offline"

    @property
    def answer_model(self) -> str:
        return self.llm_model or DEFAULT_MODELS.get(self.provider, "offline")

    @property
    def routing_model(self) -> str:
        return self.router_model or self.answer_model

    @property
    def docs_dir(self) -> Path:
        return self.data_dir / "docs"

    @property
    def overrides_dir(self) -> Path:
        return self.data_dir / "overrides"

    @property
    def db_path(self) -> Path:
        return self.var_dir / "insuretutor.sqlite3"

    @property
    def index_dir(self) -> Path:
        return self.var_dir / "index"


@lru_cache
def get_settings() -> Settings:
    return Settings()
