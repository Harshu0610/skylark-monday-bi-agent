"""Application configuration. Every secret enters the process here and nowhere else."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Monday.com (read-only) -------------------------------------------
    monday_api_token: str = ""
    monday_api_url: str = "https://api.monday.com/v2"
    monday_api_version: str = "2024-10"

    # Boards are resolved by NAME so a re-import doesn't break the app.
    # An explicit ID, if provided, wins.
    monday_deals_board_name: str = "Deals"
    monday_work_orders_board_name: str = "Work Orders"
    monday_deals_board_id: str | None = None
    monday_work_orders_board_id: str | None = None

    monday_page_size: int = 100
    monday_timeout_seconds: float = 30.0
    monday_cache_ttl_seconds: int = 300

    # --- LLM provider ------------------------------------------------------
    # Provider-abstracted so the same code runs on a free hosted tier, a paid
    # API, or a local Ollama during development.
    llm_provider: Literal["groq", "anthropic", "ollama"] = "groq"

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    # Retried automatically when the primary model is rate limited. Smaller
    # models carry a far higher free-tier token budget, so a demo asking rapid
    # questions degrades to a slightly plainer answer instead of no answer.
    groq_fallback_model: str = "openai/gpt-oss-20b"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    llm_timeout_seconds: float = 60.0

    # --- Data source -------------------------------------------------------
    # "monday" is the real integration and the default. "local_csv" reads the
    # cleaned spreadsheets from data_clean/ and exists ONLY so the stack can be
    # developed and demonstrated while the Monday boards are being set up. It is
    # labelled loudly in the UI so it can never be mistaken for live data.
    data_source: Literal["monday", "local_csv"] = "monday"

    # --- App ---------------------------------------------------------------
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"

    # Fiscal year start month. Indian companies commonly run April-March;
    # set to 1 for calendar quarters. Surfaced as a stated assumption.
    fiscal_year_start_month: int = 4

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def monday_configured(self) -> bool:
        return bool(self.monday_api_token)

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "groq":
            return bool(self.groq_api_key)
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        return True  # ollama needs no key


@lru_cache
def get_settings() -> Settings:
    return Settings()
