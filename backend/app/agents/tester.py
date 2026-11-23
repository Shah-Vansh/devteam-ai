"""Tester agent: writes the pytest suite, diagnoses failures, and fixes its own tests.

Like the Developer, it returns file contents only; workflow code writes them through
the Filesystem MCP server. Its paths are limited to `tests/` by the schema.
"""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from app.agents.common import AgentCall, context_block, files_block, generate_checked
from app.agents.developer import plan_block
from app.execution.base import ExecutionResult
from app.llm.base import LLMClient
from app.schemas.plan import ProjectPlan
from app.schemas.testing import FailureTriage, TestSuite, TriageItem

PROMPT_FILE = Path(__file__).parent / "prompts" / "tester_system.md"
MAX_FAILURES_SHOWN = 12
MAX_FAILURE_MESSAGE = 1200


FAILURES_BUDGET = 3000  # characters for all failure messages together


def _shorten(message: str, limit: int) -> str:
    """Keep the end: pytest prints the assertion and the error last."""
    message = message.strip()
    return message if len(message) <= limit else "... " + message[-limit:]


def _error_line(message: str) -> str:
    """The last non-empty line: pytest's error ("E   assert 404 == 201", an exception)."""
    lines = [line.strip() for line in message.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def failures_block(result: ExecutionResult) -> str:
    """Failure messages within a fixed budget. Found live: when all 8 tests of a project
    failed with the same error, the 8 full messages pushed the triage request over the
    free tier's 8,000 tokens per minute. Identical errors are shown once."""
    lines = [f"<test_results passed={result.passed} failed={result.failed} errors={result.errors}>"]
    shown = result.failures[:MAX_FAILURES_SHOWN]
    first_with: dict[str, str] = {}
    distinct = len({_error_line(c.message) for c in shown}) or 1
    limit = max(300, min(MAX_FAILURE_MESSAGE, FAILURES_BUDGET // distinct))
    for case in shown:
        lines.append(f"--- {case.name} ({case.outcome})")
        key = _error_line(case.message)
        if key and key in first_with:
            lines.append(f"(same error as {first_with[key]})")
            continue
        first_with[key] = case.name
        lines.append(_shorten(case.message, limit))
    if len(result.failures) > MAX_FAILURES_SHOWN:
        lines.append(f"... {len(result.failures) - MAX_FAILURES_SHOWN} more failures not shown")
    lines.append("</test_results>")
    return "\n".join(lines)


def _test_key(name: str) -> list[str]:
    text = name.strip().lower().replace("\\", "/").replace(".py", "")
    return [part for part in re.split(r"[/:.]+", text) if part]


def same_test(given: str, actual: str) -> bool:
    """Models write test names in several styles (`tests/test_a.py::test_x`,
    `tests.test_a.test_x`, just the module for a collection error, or just the function
    `test_x`). Treat names as the same if one is a prefix of the other after normalising
    separators, or if the given name is only a test function name that ends the other."""
    a, b = _test_key(given), _test_key(actual)
    shorter, longer = sorted((a, b), key=len)
    if not shorter:
        return False
    if longer[: len(shorter)] == shorter:
        return True
    # A bare function name ("test_x") for "tests/test_a.py::test_x". Only a single
    # test_* part counts, so a module name alone cannot match another module's tests.
    return len(a) == 1 and a[0].startswith("test") and b[-1] == a[0]


SHARED_TEST_FILES = ("tests/conftest.py", "tests/__init__.py")


def relevant_test_files(test_files: Mapping[str, str], names: Sequence[str]) -> dict[str, str]:
    """Only the test files a set of tests or file names refers to, plus the shared fixtures.

    Found live: with 19 tests in four files and one failure, sending every test file made
    the triage request larger than the free tier's 8,000 tokens per minute, so it could
    never be sent. If nothing matches (an unusual name), every file is kept."""
    keys = [_test_key(n) for n in names]

    def wanted(path: str) -> bool:
        module = _test_key(path)
        return any(k[: len(module)] == module or k == module for k in keys)

    picked = {p: c for p, c in test_files.items() if wanted(p)}
    if not picked:
        return dict(test_files)
    shared = {p: c for p, c in test_files.items() if p in SHARED_TEST_FILES}
    return {**shared, **picked}


class Tester:
    __test__ = False  # not a pytest test class, despite the name

    agent_name = "tester"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._system_prompt = PROMPT_FILE.read_text(encoding="utf-8")

    def _ask(self, user: str, schema, check) -> AgentCall:
        return generate_checked(
            self._llm,
            system=self._system_prompt,
            user=user,
            schema=schema,
            agent=self.agent_name,
            check=check,
        )

    def write_tests(self, plan: ProjectPlan, app_files: Mapping[str, str]) -> AgentCall[TestSuite]:
        user = (
            f"{plan_block(plan)}\n\n{context_block(app_files)}\n\n"
            "Write the pytest suite for this project."
        )

        def check(suite: TestSuite) -> list[str]:
            if not any(Path(f.path).name.startswith("test_") for f in suite.files):
                return ["no test_*.py file was returned"]
            return []

        return self._ask(user, TestSuite, check)

    def triage(
        self,
        plan: ProjectPlan,
        app_files: Mapping[str, str],
        test_files: Mapping[str, str],
        result: ExecutionResult,
    ) -> AgentCall[FailureTriage]:
        failing = {c.name for c in result.failures[:MAX_FAILURES_SHOWN]}
        user = "\n\n".join(
            (
                plan_block(plan),
                context_block(app_files),
                "Tests (the files with failing tests, and shared fixtures):\n"
                + files_block(relevant_test_files(test_files, sorted(failing)), numbered=True),
                failures_block(result),
                "Classify every failing test shown above.",
            )
        )

        def check(triage: FailureTriage) -> list[str]:
            problems = []
            missing = sorted(
                name for name in failing if not any(same_test(i.test, name) for i in triage.items)
            )
            if missing:
                given = ", ".join(i.test for i in triage.items) or "none"
                problems.append(
                    f"these failing tests were not classified: {', '.join(missing)} "
                    f"(names given: {given}); use the names exactly as listed"
                )
            for item in triage.items:
                if item.cause == "bad_code" and item.file not in app_files:
                    problems.append(
                        f"{item.test}: bad_code must name an app file, not {item.file!r}"
                    )
                if item.cause == "bad_test" and item.file not in test_files:
                    problems.append(
                        f"{item.test}: bad_test must name a test file, not {item.file!r}"
                    )
            return problems

        return self._ask(user, FailureTriage, check)

    def fix_tests(
        self,
        plan: ProjectPlan,
        app_files: Mapping[str, str],
        test_files: Mapping[str, str],
        items: Sequence[TriageItem],
    ) -> AgentCall[TestSuite]:
        problems = "\n".join(
            f"- {i.test} ({i.file}): {i.reason}\n  Fix: {i.suggested_fix}" for i in items
        )
        user = "\n\n".join(
            (
                plan_block(plan),
                context_block(app_files),
                "Current tests (the files to fix, and shared fixtures):\n"
                + files_block(relevant_test_files(test_files, [i.file for i in items])),
                f"<test_problems>\n{problems}\n</test_problems>",
                "Fix these test problems. Return only the test files you change, each with "
                "its full new content. Tests must match the plan and the code as written.",
            )
        )

        def check(suite: TestSuite) -> list[str]:
            if not suite.files:
                return ["you returned no files; change at least one test file"]
            if all(test_files.get(f.path) == f.content for f in suite.files):
                return ["none of the returned test files differ from the current ones"]
            return []

        return self._ask(user, TestSuite, check)
