import pytest

from app.core.config import Settings
from app.llm.base import LLMConfigError
from app.llm.factory import build_llm_client


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_unknown_provider_fails_fast():
    with pytest.raises(LLMConfigError, match="not supported"):
        build_llm_client(settings(llm_provider="nope", llm_api_key="k", llm_model="m"))


def test_missing_key_fails_fast():
    with pytest.raises(LLMConfigError, match="LLM_API_KEY"):
        build_llm_client(settings(llm_provider="groq", llm_api_key=None, llm_model="m"))


def test_missing_model_fails_fast():
    with pytest.raises(LLMConfigError, match="LLM_MODEL"):
        build_llm_client(settings(llm_provider="groq", llm_api_key="k", llm_model=""))


def test_model_override():
    client = build_llm_client(
        settings(llm_provider="groq", llm_api_key="k", llm_model="default"), model="other"
    )
    assert client.model == "other"
