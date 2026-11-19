"""A whole run: plan -> develop and review -> tests -> sandbox -> triage and fix.

Phase 5 turns this into a LangGraph graph with checkpoints and pauses. The steps,
limits and outcomes stay the same:

    develop_and_review --FAILED_REVIEW--> stop
         |
    Tester writes tests -> human approves execution? --no--> NOT_EXECUTED
         |
    run tests in the sandbox --PASSED--> TESTS_PASSED
         |                  --NOT_EXECUTED (no sandbox)--> NOT_EXECUTED
         |                  --ERROR (install, timeout, sandbox)--> ERROR
      FAILED, fix_rounds < max -> triage -> bad_code: Developer fixes
                                         -> bad_test: Tester fixes
                                         -> only environment: FAILED_TESTS
      FAILED, fix_rounds == max -> FAILED_TESTS

A passed review never counts as passed tests; the two are reported separately.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Literal

import anyio.to_thread

from app.agents.common import AgentOutputError
from app.agents.developer import Developer, DeveloperInputError
from app.agents.reviewer import Reviewer
from app.agents.tester import Tester
from app.execution.base import CodeExecutor, ExecutionResult, ExecutionSpec
from app.execution.packages import allowed_names_text, select_packages
from app.llm.base import LLMRequestError, LLMResponseError
from app.mcp_clients.filesystem import FilesystemClient
from app.pipeline.budget import LLMBudget
from app.pipeline.develop import DevelopResult, develop_and_review, write_changes
from app.schemas.plan import ProjectPlan
from app.schemas.review import Finding, ReviewReport
from app.schemas.testing import FailureTriage, is_test_path

RunStatus = Literal["TESTS_PASSED", "FAILED_REVIEW", "FAILED_TESTS", "NOT_EXECUTED", "ERROR"]


@dataclass
class TestRound:
    __test__ = False  # not a pytest test class, despite the name

    round: int
    result: ExecutionResult
    triage: FailureTriage | None = None


@dataclass
class RunResult:
    status: RunStatus
    stop_reason: str
    develop: DevelopResult
    test_rounds: list[TestRound] = field(default_factory=list)
    fix_rounds: int = 0

    @property
    def last_test_result(self) -> ExecutionResult | None:
        return self.test_rounds[-1].result if self.test_rounds else None


async def read_all(fs: FilesystemClient, workspace: str) -> dict[str, str]:
    return {p: await fs.read_file(workspace, p) for p in await fs.list_files(workspace)}


def split_files(files: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    tests = {p: c for p, c in files.items() if is_test_path(p)}
    return {p: c for p, c in files.items() if p not in tests}, tests


async def build_and_test(
    plan: ProjectPlan,
    *,
    workspace: str,
    developer: Developer,
    reviewer: Reviewer,
    tester: Tester,
    executor: CodeExecutor,
    fs: FilesystemClient,
    budget: LLMBudget,
    approve_execution: Callable[[], Awaitable[bool]],
    max_review_rounds: int = 2,
    max_fix_rounds: int = 2,
    test_timeout_seconds: int = 120,
    progress: Callable[[str], None] = lambda _msg: None,
    on_report: Callable[[ReviewReport], None] = lambda _report: None,
    on_test_round: Callable[[TestRound], None] = lambda _round: None,
) -> RunResult:
    developed = await develop_and_review(
        plan,
        workspace=workspace,
        developer=developer,
        reviewer=reviewer,
        fs=fs,
        max_review_rounds=max_review_rounds,
        budget=budget,
        progress=progress,
        on_report=on_report,
    )
    run = RunResult(status="ERROR", stop_reason="", develop=developed)

    def finish(status: RunStatus, reason: str = "") -> RunResult:
        run.status, run.stop_reason = status, reason
        if reason:
            progress(reason)
        return run

    if developed.status == "FAILED_REVIEW":
        return finish("FAILED_REVIEW", developed.stop_reason)

    async def testing() -> RunResult:
        progress("tester: writing tests")
        app_files, _ = split_files(await read_all(fs, workspace))
        suite = await anyio.to_thread.run_sync(tester.write_tests, plan, app_files)
        budget.spend(suite.usages)
        written = await write_changes(fs, workspace, suite.data)
        progress(f"wrote {', '.join(written)}")

        if not await approve_execution():
            return finish("NOT_EXECUTED", "test execution was not approved")

        while True:
            files = await read_all(fs, workspace)
            app_files, test_files = split_files(files)

            selection = select_packages(app_files.get("requirements.txt", ""))
            if selection.rejected:
                # Never install unknown packages; ask the Developer to use allowed ones instead.
                if run.fix_rounds >= max_fix_rounds:
                    return finish("FAILED_TESTS", f"packages not allowed: {selection.rejected}")
                run.fix_rounds += 1
                progress(f"fix {run.fix_rounds}: packages not allowed {selection.rejected}")
                finding = Finding(
                    source="sandbox",
                    file="requirements.txt",
                    line=0,
                    severity="high",
                    category="spec",
                    message="packages not available in the sandbox: "
                    + ", ".join(selection.rejected),
                    suggested_fix=f"Use only these packages: {allowed_names_text()}; change the "
                    "code that imports anything else.",
                )
                await _developer_fix(developer, plan, app_files, [finding], fs, workspace, budget)
                continue

            progress(f"executor ({executor.name}): running tests")
            spec = ExecutionSpec(packages=selection.install, timeout_seconds=test_timeout_seconds)
            result = await anyio.to_thread.run_sync(executor.run_tests, files, spec)
            test_round = TestRound(round=len(run.test_rounds) + 1, result=result)
            run.test_rounds.append(test_round)
            on_test_round(test_round)  # saved now; saved again once triage is added
            progress(
                f"tests {test_round.round}: {result.status} "
                f"(passed {result.passed}, failed {result.failed}, errors {result.errors}, "
                f"{result.duration_ms / 1000:.1f}s)"
            )

            if result.status == "PASSED":
                return finish("TESTS_PASSED")
            if result.status == "NOT_EXECUTED":
                return finish("NOT_EXECUTED", result.detail)
            if result.status == "ERROR":
                return finish("ERROR", f"test run failed: {result.detail}")
            if run.fix_rounds >= max_fix_rounds:
                return finish(
                    "FAILED_TESTS",
                    f"{len(result.failures)} failing test(s) after {run.fix_rounds} fix round(s)",
                )

            progress("tester: triaging failures")
            triage_call = await anyio.to_thread.run_sync(
                partial(tester.triage, plan, app_files, test_files, result)
            )
            budget.spend(triage_call.usages)
            test_round.triage = triage = triage_call.data
            on_test_round(test_round)

            code_items = [i for i in triage.items if i.cause == "bad_code"]
            test_items = [i for i in triage.items if i.cause == "bad_test"]
            env_items = [i for i in triage.items if i.cause == "environment"]
            progress(
                f"triage: bad_code {len(code_items)}, bad_test {len(test_items)}, "
                f"environment {len(env_items)}"
            )
            if not code_items and not test_items:
                return finish("FAILED_TESTS", f"environment problem: {triage.summary}")

            run.fix_rounds += 1
            if code_items:
                findings = [
                    Finding(
                        source="tests",
                        file=i.file,
                        line=0,
                        severity="high",
                        category="bug",
                        message=f"{i.test} fails: {i.reason}",
                        suggested_fix=i.suggested_fix,
                    )
                    for i in code_items
                ]
                progress(f"developer: fix round {run.fix_rounds}")
                await _developer_fix(developer, plan, app_files, findings, fs, workspace, budget)
            if test_items:
                progress(f"tester: fixing tests, round {run.fix_rounds}")
                fixed = await anyio.to_thread.run_sync(
                    partial(tester.fix_tests, plan, app_files, test_files, test_items)
                )
                budget.spend(fixed.usages)
                await write_changes(fs, workspace, fixed.data)

    # One policy for every agent step after review: a model that cannot give a usable
    # answer ends the run as FAILED_TESTS; an unreachable provider (or used-up quota) is
    # an ERROR. Either way the rounds recorded so far are kept in the result.
    try:
        return await testing()
    except (AgentOutputError, DeveloperInputError, LLMResponseError) as exc:
        return finish("FAILED_TESTS", f"an agent could not produce a usable answer: {exc}")
    except LLMRequestError as exc:
        return finish("ERROR", f"LLM provider request failed: {exc}")


async def _developer_fix(
    developer: Developer,
    plan: ProjectPlan,
    app_files: dict[str, str],
    findings: list[Finding],
    fs: FilesystemClient,
    workspace: str,
    budget: LLMBudget,
) -> None:
    revised = await anyio.to_thread.run_sync(partial(developer.revise, plan, app_files, findings))
    budget.spend(revised.usages)
    await write_changes(fs, workspace, revised.data)
