"""The `CodeExecutor` interface and its result types.

The workflow depends only on this interface. `E2BExecutor` runs tests in a remote
microVM; `StaticOnlyExecutor` never runs anything and says so (`NOT_EXECUTED`), so a
missing sandbox can never look like passing tests.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import BaseModel

ExecutionStatus = Literal["PASSED", "FAILED", "ERROR", "NOT_EXECUTED"]
CaseOutcome = Literal["passed", "failed", "error", "skipped"]

MAX_MESSAGE_CHARS = 2000
MAX_OUTPUT_CHARS = 4000


class TestCaseResult(BaseModel):
    __test__ = False  # not a pytest test class, despite the name

    name: str  # e.g. tests/test_todos.py::test_create
    outcome: CaseOutcome
    message: str = ""


class ExecutionResult(BaseModel):
    status: ExecutionStatus
    executor: str
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    duration_ms: int = 0
    cases: list[TestCaseResult] = []
    # ERROR and NOT_EXECUTED explain themselves here
    detail: str = ""
    output_tail: str = ""

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors + self.skipped

    @property
    def failures(self) -> list[TestCaseResult]:
        return [c for c in self.cases if c.outcome in ("failed", "error")]


@dataclass(frozen=True)
class ExecutionSpec:
    packages: list[str] = field(default_factory=list)
    timeout_seconds: int = 120


class CodeExecutor(Protocol):
    name: str

    def run_tests(self, files: dict[str, str], spec: ExecutionSpec) -> ExecutionResult:
        """Run the project's pytest suite. Never raises for problems inside the run;
        they are reported as `ERROR` with a `detail`."""
        ...


def tail(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    return text if len(text) <= limit else "..." + text[-limit:]
