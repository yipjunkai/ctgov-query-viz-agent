"""Runtime configuration, sourced from environment / .env.

Provider selection is deliberate: OpenRouter first (the user's preference; OpenAI-compatible), the
OpenAI key as fallback, and — when neither key is present — a deterministic rule-based planner so a
reviewer can clone-and-run with zero secrets.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openrouter_api_key: str | None = None
    openai_api_key: str | None = None

    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "openai/gpt-4o-mini"
    openai_model: str = "gpt-4o-mini"

    request_timeout: float = 30.0
    # Refuse (rather than aggregate) any query whose match set exceeds this — see the too-broad
    # guardrail. Kept well under the paging backstop so exact counts stay exact.
    too_broad_threshold: int = 10000


@lru_cache
def get_settings() -> Settings:
    return Settings()
