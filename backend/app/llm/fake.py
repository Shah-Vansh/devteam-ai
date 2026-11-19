"""A fake LLM client for tests: returns prepared responses, records every request."""

from dataclasses import dataclass, field

from pydantic import BaseModel

from app.llm.base import LLMResponseError, LLMUsage, StructuredResult, T


@dataclass
class RecordedRequest:
    system: str
    user: str
    schema: type[BaseModel]
    agent: str


@dataclass
class FakeLLMClient:
    """Each call pops the next response. A response may be a dict, a model, or an exception."""

    responses: list[object]
    model: str = "fake-model"
    requests: list[RecordedRequest] = field(default_factory=list)

    def generate_structured(
        self, *, system: str, user: str, schema: type[T], agent: str
    ) -> StructuredResult[T]:
        self.requests.append(RecordedRequest(system, user, schema, agent))
        if not self.responses:
            raise LLMResponseError("FakeLLMClient has no responses left")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        data = response if isinstance(response, schema) else schema.model_validate(response)
        usage = LLMUsage(model=self.model, input_tokens=100, output_tokens=200, latency_ms=1)
        return StructuredResult(data=data, usage=usage, attempts=1)
