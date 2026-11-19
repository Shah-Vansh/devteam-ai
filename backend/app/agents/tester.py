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


def failures_block(result: ExecutionResult) -> str:
    lines = [f"<test_results passed={result.passed} failed={result.failed} errors={result.errors}>"]
    for case in result.failures[:MAX_FAILURES_SHOWN]:
        lines.append(f"--- {case.name} ({case.outcome})")
        lines.append(case.message[:MAX_FAILURE_MESSAGE])
    if len(result.failures) > MAX_FAILURES_SHOWN:
        lines.append(f"... {len(result.failures) - MAX_FAILURES_SHOWN} more failures not shown")
    lines.append("</test_results>")
    return "\n".join(lines)


def _test_key(name: str) -> list[str]:
    text = name.strip().lower().replace("\\", "/").replace(".py", "")
    return [part for part in re.split(r"[/:.]+", text) if part]


def same_test(given: str, actual: str) -> bool:
    """Models write test names in several styles (`tests/test_a.py::test_x`,
    `tests.test_a.test_x`, or just the module for a collection error). Treat names as the
    same if one is a prefix of the other after normalising separators."""
    a, b = _test_key(given), _test_key(actual)
    shorter, longer = sorted((a, b), key=len)
    return bool(shorter) and longer[: len(shorter)] == shorter


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
                "Tests:\n" + files_block(test_files, numbered=True),
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
                problems.append(f"these failing tests were not classified: {', '.join(missing)}")
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
                "Current tests:\n" + files_block(test_files),
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
