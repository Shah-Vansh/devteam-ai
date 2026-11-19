"""The provider-agnostic interface every agent uses to talk to a language model.

Agents depend only on `LLMClient`, never on a vendor SDK. Swapping providers or
using a fake client in tests needs no change to agent code.
"""

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMUsage:
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass(frozen=True)
class StructuredResult[T: BaseModel]:
    data: T
    usage: LLMUsage
    attempts: int


class LLMError(Exception):
    """Base class for every LLM failure the rest of the system must handle."""


class LLMConfigError(LLMError):
    """The client cannot be built: missing key, unknown provider, missing model."""


class LLMRequestError(LLMError):
    """The provider could not be reached or rejected the request (after SDK retries)."""


class LLMResponseError(LLMError):
    """The provider answered, but the output never matched the schema."""


class LLMClient(Protocol):
    @property
    def model(self) -> str: ...

    def generate_structured(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        agent: str,
    ) -> StructuredResult[T]:
        """Return `schema` filled in by the model, already validated by Pydantic."""
        ...
