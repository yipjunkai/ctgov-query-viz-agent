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
    # Planning is light structured extraction, so a *mini* is the sweet spot (cost/latency). Any
    # model on the key's allowlist works — override via OPENROUTER_MODEL / OPENAI_MODEL.
    openrouter_model: str = "openai/gpt-5-mini"
    openai_model: str = "gpt-5-mini"

    # Left unset (the model's default) for cross-model compatibility — some models reject a
    # non-default temperature. Set PLANNER_TEMPERATURE=0 for deterministic planning where supported.
    planner_temperature: float | None = None

    request_timeout: float = 30.0
    # Refuse (rather than aggregate) any query whose match set exceeds this — see the too-broad
    # guardrail. Kept well under the paging backstop so exact counts stay exact.
    too_broad_threshold: int = 10000


@lru_cache
def get_settings() -> Settings:
    return Settings()
