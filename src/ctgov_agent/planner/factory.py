"""Build the configured planner: OpenRouter → OpenAI → rule-based fallback."""

from openai import AsyncOpenAI

from ctgov_agent.config import Settings
from ctgov_agent.planner.base import Planner
from ctgov_agent.planner.llm import LLMPlanner, OpenAIChatModel
from ctgov_agent.planner.rules import RuleBasedPlanner


def build_planner(settings: Settings) -> Planner:
    if settings.openrouter_api_key:
        client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            timeout=settings.request_timeout,
        )
        model = OpenAIChatModel(
            client, settings.openrouter_model, temperature=settings.planner_temperature
        )
        return LLMPlanner(model)
    if settings.openai_api_key:
        client = AsyncOpenAI(api_key=settings.openai_api_key, timeout=settings.request_timeout)
        model = OpenAIChatModel(
            client, settings.openai_model, temperature=settings.planner_temperature
        )
        return LLMPlanner(model)
    return RuleBasedPlanner()
