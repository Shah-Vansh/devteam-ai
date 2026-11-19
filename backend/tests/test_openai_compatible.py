"""Tests the retry and error logic without any network call, using a stand-in SDK object."""

from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import ValidationError

from app.llm.base import LLMRequestError, LLMResponseError
from app.llm.openai_compatible import OpenAICompatibleClient
from app.schemas.plan import ProjectPlan


def validation_error() -> ValidationError:
    try:
        ProjectPlan.model_validate({})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected a ValidationError")


def ok_response(plan: ProjectPlan):
    message = SimpleNamespace(parsed=plan, refusal=None)
    usage = SimpleNamespace(prompt_tokens=500, completion_tokens=900)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


class StubSDK:
    """Mimics `openai.OpenAI().chat.completions.parse` with scripted outcomes."""

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_client(sdk: StubSDK) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(api_key="k", model="m", sdk_client=sdk, validation_retries=1)


def call(client: OpenAICompatibleClient):
    return client.generate_structured(system="s", user="u", schema=ProjectPlan, agent="planner")


def test_success_returns_data_and_usage(todo_plan_data):
    plan = ProjectPlan.model_validate(todo_plan_data)
    result = call(make_client(StubSDK([ok_response(plan)])))
    assert result.data == plan
    assert result.usage.input_tokens == 500
    assert result.usage.output_tokens == 900
    assert result.attempts == 1


def test_invalid_output_is_retried_once(todo_plan_data):
    plan = ProjectPlan.model_validate(todo_plan_data)
    sdk = StubSDK([validation_error(), ok_response(plan)])
    result = call(make_client(sdk))
    assert sdk.calls == 2
    assert result.attempts == 2


def test_gives_up_after_retries():
    sdk = StubSDK([validation_error(), validation_error()])
    with pytest.raises(LLMResponseError, match="after 2 attempts"):
        call(make_client(sdk))


def test_empty_parsed_output_counts_as_failure():
    empty = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=None, refusal="no"))], usage=None
    )
    with pytest.raises(LLMResponseError):
        call(make_client(StubSDK([empty, empty])))


def bad_request(code: str, message: str) -> openai.BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "https://example.test"))
    body = {"error": {"code": code, "message": message}}
    return openai.BadRequestError(message, response=response, body=body)


def test_provider_schema_rejection_is_retried(todo_plan_data):
    plan = ProjectPlan.model_validate(todo_plan_data)
    rejection = bad_request("json_validate_failed", "See 'failed_generation' for details")
    sdk = StubSDK([rejection, ok_response(plan)])
    result = call(make_client(sdk))
    assert sdk.calls == 2
    assert result.attempts == 2


def test_other_bad_requests_are_not_retried():
    sdk = StubSDK([bad_request("model_not_found", "unknown model")])
    with pytest.raises(LLMRequestError, match="rejected"):
        call(make_client(sdk))
    assert sdk.calls == 1


def test_provider_errors_are_not_retried_here():
    error = openai.APIConnectionError(request=httpx.Request("POST", "https://example.test"))
    sdk = StubSDK([error])
    with pytest.raises(LLMRequestError):
        call(make_client(sdk))
    assert sdk.calls == 1
