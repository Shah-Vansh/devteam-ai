"""Builds the configured LLM client from settings. The only place that knows provider names."""

from app.core.config import Settings
from app.llm.base import LLMClient, LLMConfigError
from app.llm.openai_compatible import OpenAICompatibleClient

# Providers reachable through the OpenAI-compatible client, with their default URLs.
OPENAI_COMPATIBLE_PROVIDERS = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": None,
}


def build_llm_client(settings: Settings, model: str | None = None) -> LLMClient:
    """Fail fast with a clear message if configuration is incomplete."""
    provider = settings.llm_provider.strip().lower()
    if provider not in OPENAI_COMPATIBLE_PROVIDERS:
        known = ", ".join(sorted(OPENAI_COMPATIBLE_PROVIDERS))
        raise LLMConfigError(f"LLM_PROVIDER '{provider}' is not supported (known: {known})")
    if settings.llm_api_key is None:
        raise LLMConfigError("LLM_API_KEY is not set in the root .env")
    chosen_model = model or settings.llm_model
    if not chosen_model:
        raise LLMConfigError("LLM_MODEL is not set in the root .env")

    return OpenAICompatibleClient(
        api_key=settings.llm_api_key.get_secret_value(),
        model=chosen_model,
        base_url=settings.llm_base_url or OPENAI_COMPATIBLE_PROVIDERS[provider],
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
        reasoning_effort=settings.llm_reasoning_effort,
    )
