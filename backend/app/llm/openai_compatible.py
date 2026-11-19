"""LLM client for any provider with an OpenAI-compatible API (Groq, OpenAI, ...).

Two kinds of retry, handled in different places:
- Transport problems (timeouts, 429 rate limits, 5xx): retried by the OpenAI SDK
  itself with exponential backoff (`max_retries`).
- Output problems (JSON that fails Pydantic validation): retried here, because the
  SDK cannot know our schema rules. The model is sampled again.
"""

import logging
import time
from typing import Any

import openai
from pydantic import ValidationError

from app.llm.base import (
    LLMRequestError,
    LLMResponseError,
    LLMUsage,
    StructuredResult,
    T,
)

logger = logging.getLogger(__name__)

SCHEMA_REJECTION_CODES = {"json_validate_failed"}


def is_schema_rejection(exc: openai.BadRequestError) -> bool:
    """True when a 400 means 'the model's output broke the schema', not 'bad request'."""
    if getattr(exc, "code", None) in SCHEMA_REJECTION_CODES:
        return True
    return "failed_generation" in str(exc)


def is_truncation(exc: Exception) -> bool:
    """The answer hit the output-token limit. Asking again with the same budget would
    most likely be cut off again, so this is not retried."""
    return isinstance(exc, openai.LengthFinishReasonError) or (
        "max completion tokens" in str(exc).lower()
    )


class OutputTooLongError(LLMResponseError):
    """The structured answer did not fit in the output-token limit."""


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        validation_retries: int = 1,
        max_output_tokens: int | None = None,
        reasoning_effort: str | None = None,
        sdk_client: Any | None = None,
    ) -> None:
        self._model = model
        self._validation_retries = validation_retries
        # Only sent when configured, so providers that do not know them are unaffected.
        self._extra: dict[str, Any] = {}
        if max_output_tokens:
            self._extra["max_completion_tokens"] = max_output_tokens
        if reasoning_effort:
            self._extra["reasoning_effort"] = reasoning_effort
        # `sdk_client` lets tests inject a fake instead of a real network client.
        self._client = sdk_client or openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    @property
    def model(self) -> str:
        return self._model

    def generate_structured(
        self, *, system: str, user: str, schema: type[T], agent: str
    ) -> StructuredResult[T]:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        attempts = 1 + self._validation_retries
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            start = time.perf_counter()
            try:
                # `parse` sends our Pydantic model as a strict JSON schema and
                # validates the reply with the same model.
                response = self._client.chat.completions.parse(
                    model=self._model,
                    messages=messages,
                    response_format=schema,
                    **self._extra,
                )
            except ValidationError as exc:
                last_error = exc
                self._log_failure(agent, attempt, "invalid_output", exc)
                continue
            except openai.LengthFinishReasonError as exc:
                self._log_failure(agent, attempt, "output_too_long", exc)
                raise self._too_long(agent) from exc
            except openai.BadRequestError as exc:
                if is_truncation(exc):
                    self._log_failure(agent, attempt, "output_too_long", exc)
                    raise self._too_long(agent) from exc
                if not is_schema_rejection(exc):
                    raise LLMRequestError(f"{agent}: request rejected: {exc}") from exc
                # Some providers (Groq) check the schema server-side and answer 400
                # instead of returning invalid JSON. Same meaning: sample again.
                last_error = exc
                self._log_failure(agent, attempt, "schema_rejected_by_provider", exc)
                continue
            except openai.APIError as exc:
                # The SDK has already retried transient errors; give up now.
                raise LLMRequestError(f"{agent}: provider request failed: {exc}") from exc

            latency_ms = int((time.perf_counter() - start) * 1000)
            message = response.choices[0].message
            if message.parsed is None:
                last_error = LLMResponseError(message.refusal or "empty structured output")
                self._log_failure(agent, attempt, "empty_output", last_error)
                continue

            usage = LLMUsage(
                model=self._model,
                input_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
                latency_ms=latency_ms,
            )
            logger.info(
                "llm_call",
                extra={
                    "fields": {
                        "agent": agent,
                        "model": usage.model,
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                        "latency_ms": usage.latency_ms,
                        "attempt": attempt,
                    }
                },
            )
            return StructuredResult(data=message.parsed, usage=usage, attempts=attempt)

        raise LLMResponseError(
            f"{agent}: no valid {schema.__name__} after {attempts} attempts: {last_error}"
        ) from last_error

    def _too_long(self, agent: str) -> OutputTooLongError:
        limit = self._extra.get("max_completion_tokens", "the provider default")
        return OutputTooLongError(
            f"{agent}: answer exceeded the output-token limit ({limit}); raise "
            "LLM_MAX_OUTPUT_TOKENS, lower LLM_REASONING_EFFORT, or ask for less per call"
        )

    def _log_failure(self, agent: str, attempt: int, reason: str, exc: Exception) -> None:
        logger.warning(
            "llm_call_failed",
            extra={
                "fields": {
                    "agent": agent,
                    "model": self._model,
                    "attempt": attempt,
                    "reason": reason,
                    "error": str(exc)[:300],
                }
            },
        )
