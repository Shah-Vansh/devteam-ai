"""The workflow's nodes. Each reads the state, does one step, and returns only the fields
it changes. Routing decisions live in `graph.py`; limits are applied here, where the
step that would exceed them runs, so routers stay simple functions of the state.

Errors never escape a node (except LangGraph's own interrupt signal): `guard` turns them
into a terminal status, so every run ends in a defined state.
"""

import functools
from collections.abc import Awaitable, Callable
from typing import Any

import anyio.to_thread
from langgraph.runtime import Runtime
from langgraph.types import interrupt

from app.agents.common import AgentCall, AgentOutputError
from app.agents.developer import DeveloperInputError
from app.agents.planner import PlannerInputError
from app.execution.base import ExecutionResult, ExecutionSpec
from app.execution.packages import allowed_names_text, select_packages
from app.llm.base import LLMRequestError, LLMResponseError
from app.mcp_clients.filesystem import FilesystemToolError, McpCallError
from app.schemas.plan import Clarification, ProjectPlan
from app.schemas.review import Finding, ReviewReport
from app.schemas.testing import TriageItem
from app.workflow.state import RunState, WorkflowDeps
from app.workflow.workspace_io import new_workspace_name, read_all, split_files, write_changes

Node = Callable[[RunState, Runtime[WorkflowDeps]], Awaitable[dict[str, Any]]]


class LLMBudgetExceeded(Exception):
    """The run would need more LLM calls than MAX_LLM_CALLS_PER_RUN allows."""


# What a model that cannot give a usable answer means, depending on the stage.
FAILED_STATUS = {"plan": "ERROR", "review": "FAILED_REVIEW", "test": "FAILED_TESTS"}


def guard(stage: str) -> Callable[[Node], Node]:
    def wrap(node: Node) -> Node:
        @functools.wraps(node)
        async def run(state: RunState, runtime: Runtime[WorkflowDeps]) -> dict[str, Any]:
            try:
                return await node(state, runtime)
            except (
                AgentOutputError,
                DeveloperInputError,
                LLMResponseError,
                PlannerInputError,
            ) as exc:
                status, reason = FAILED_STATUS[stage], f"{node.__name__}: no usable answer: {exc}"
            except LLMBudgetExceeded as exc:
                status, reason = "ERROR", str(exc)
            except LLMRequestError as exc:
                status, reason = "ERROR", f"LLM provider request failed: {exc}"
            except (FilesystemToolError, McpCallError) as exc:
                status, reason = "ERROR", f"workspace error: {exc}"
            runtime.context.progress(reason)
            return {"status": status, "stop_reason": reason[:2000]}

        return run

    return wrap


def plan_of(state: RunState) -> ProjectPlan:
    return ProjectPlan.model_validate(state["plan"])


def spend(state: RunState, deps: WorkflowDeps, call: Any) -> dict[str, int]:
    """Add a call's token use to the run's totals (`call` has `.usages`), enforcing the
    per-run limit across every stage and across pauses."""
    calls = state.get("llm_calls", 0) + len(call.usages)
    if calls > deps.max_llm_calls:
        raise LLMBudgetExceeded(f"used {calls} LLM calls; limit is {deps.max_llm_calls}")
    return {
        "llm_calls": calls,
        "input_tokens": state.get("input_tokens", 0) + sum(u.input_tokens for u in call.usages),
        "output_tokens": state.get("output_tokens", 0) + sum(u.output_tokens for u in call.usages),
    }


async def in_thread(func, *args):
    """Agents and executors are synchronous; keep the event loop (and MCP) responsive."""
    return await anyio.to_thread.run_sync(functools.partial(func, *args))


# ---------- planning ----------


@guard("plan")
async def plan(state: RunState, runtime: Runtime[WorkflowDeps]) -> dict[str, Any]:
    deps = runtime.context
    update: dict[str, Any] = {"status": "RUNNING"}
    if state.get("plan") is None:
        deps.progress("planner: planning")
        clarifications = [Clarification(**c) for c in state.get("clarifications", [])]
        result = await in_thread(deps.planner.plan, state["requirement"], clarifications)
        update |= spend(state, deps, AgentCall(data=result.plan, usages=[result.usage]))
        update["plan"] = result.plan.model_dump()
        project = result.plan
    else:
        project = plan_of(state)
    if not state.get("workspace"):
        update["workspace"] = new_workspace_name(project.project_name)
    deps.progress(f"plan: {project.project_name}, {len(project.files)} files")
    # Ask at most once; after answers (or a skip) the plan proceeds on its assumptions.
    will_ask = (
        bool(project.open_questions) and deps.ask_clarifications and not state.get("clarified")
    )
    if not will_ask:
        update["clarified"] = True
    return update


async def clarify(state: RunState, runtime: Runtime[WorkflowDeps]) -> dict[str, Any]:
    """Human pause. Resume with {"answers": [...]} (empty answer = keep the assumption)
    or {"action": "cancel"}. No side effects before `interrupt`: the node is re-run from
    the top when the run resumes."""
    questions = plan_of(state).open_questions
    reply = interrupt({"kind": "clarify", "questions": questions})
    if reply.get("action") == "cancel":
        return {"status": "CANCELLED", "stop_reason": "cancelled while answering questions"}
    answers = list(reply.get("answers", []))
    clarifications = [
        {"question": q, "answer": a.strip()}
        for q, a in zip(questions, answers, strict=False)
        if a and a.strip()
    ]
    if not clarifications:
        return {"clarified": True}
    runtime.context.progress(f"re-planning with {len(clarifications)} answer(s)")
    # Dropping the plan makes the plan node run the Planner again with the answers.
    return {"clarified": True, "clarifications": clarifications, "plan": None}


# ---------- develop and review ----------


@guard("review")
async def develop(state: RunState, runtime: Runtime[WorkflowDeps]) -> dict[str, Any]:
    deps = runtime.context
    deps.progress("developer: writing files")
    call = await in_thread(deps.developer.generate, plan_of(state))
    update = spend(state, deps, call)
    written = await write_changes(deps.fs, state["workspace"], call.data)
    deps.progress(f"wrote {len(written)} files")
    return update


@guard("review")
async def review(state: RunState, runtime: Runtime[WorkflowDeps]) -> dict[str, Any]:
    deps = runtime.context
    reports = list(state.get("reports", []))
    deps.progress(f"reviewer: round {len(reports) + 1}")
    result = await deps.reviewer.review(
        workspace=state["workspace"],
        plan=plan_of(state),
        fs=deps.fs.read_only(),
        round=len(reports) + 1,
    )
    update: dict[str, Any] = spend(state, deps, result)
    report = result.report
    reports.append(report.model_dump() | {"verdict": report.verdict})
    update["reports"] = reports
    counts = report.counts()
    deps.progress(
        f"review {report.round}: {report.verdict} "
        f"(high {counts['high']}, medium {counts['medium']}, low {counts['low']})"
    )
    rounds = state.get("review_rounds", 0)
    if report.verdict == "changes_needed" and rounds >= deps.max_review_rounds:
        update["status"] = "FAILED_REVIEW"
        update["stop_reason"] = f"high-severity findings remain after {rounds} revision(s)"
    return update


@guard("review")
async def revise(state: RunState, runtime: Runtime[WorkflowDeps]) -> dict[str, Any]:
    deps = runtime.context
    report = ReviewReport.model_validate(state["reports"][-1])
    rounds = state.get("review_rounds", 0) + 1
    deps.progress(f"developer: revision {rounds} ({len(report.to_fix)} findings to fix)")
    app_files, _ = split_files(await read_all(deps.fs, state["workspace"]))
    call = await in_thread(deps.developer.revise, plan_of(state), app_files, report.to_fix)
    update = spend(state, deps, call)
    changed = await write_changes(deps.fs, state["workspace"], call.data)
    deps.progress(f"updated {', '.join(changed)}")
    return update | {"review_rounds": rounds}


# ---------- tests ----------


@guard("test")
async def write_tests(state: RunState, runtime: Runtime[WorkflowDeps]) -> dict[str, Any]:
    deps = runtime.context
    deps.progress("tester: writing tests")
    app_files, _ = split_files(await read_all(deps.fs, state["workspace"]))
    call = await in_thread(deps.tester.write_tests, plan_of(state), app_files)
    update = spend(state, deps, call)
    written = await write_changes(deps.fs, state["workspace"], call.data)
    deps.progress(f"wrote {', '.join(written)}")
    return update | {"tests_written": True}


async def approve(state: RunState, runtime: Runtime[WorkflowDeps]) -> dict[str, Any]:
    """Human pause before generated code is sent to the sandbox. Resume with
    {"approved": true|false} or {"action": "cancel"}."""
    deps = runtime.context
    if (
        state.get("execution_approved")
        or deps.auto_approve_execution
        or deps.executor.name == "static_only"  # nothing will run
    ):
        return {"execution_approved": True}
    reply = interrupt(
        {"kind": "execute", "executor": deps.executor.name, "workspace": state["workspace"]}
    )
    if reply.get("action") == "cancel":
        return {"status": "CANCELLED", "stop_reason": "cancelled before test execution"}
    if not reply.get("approved"):
        return {
            "execution_approved": False,
            "status": "NOT_EXECUTED",
            "stop_reason": "test execution was not approved",
        }
    return {"execution_approved": True}


@guard("test")
async def run_tests(state: RunState, runtime: Runtime[WorkflowDeps]) -> dict[str, Any]:
    deps = runtime.context
    files = await read_all(deps.fs, state["workspace"])
    app_files, _ = split_files(files)
    fix_rounds = state.get("fix_rounds", 0)

    selection = select_packages(app_files.get("requirements.txt", ""))
    if selection.rejected:
        # Unknown packages are never installed; the Developer must use allowed ones.
        if fix_rounds >= deps.max_fix_rounds:
            return {
                "status": "FAILED_TESTS",
                "stop_reason": f"packages not allowed: {', '.join(selection.rejected)}",
            }
        deps.progress(f"packages not allowed: {', '.join(selection.rejected)}")
        finding = Finding(
            source="sandbox",
            file="requirements.txt",
            line=0,
            severity="high",
            category="spec",
            message="packages not available in the sandbox: " + ", ".join(selection.rejected),
            suggested_fix=f"Use only these packages: {allowed_names_text()}; change the code "
            "that imports anything else.",
        )
        return {
            "fix_rounds": fix_rounds + 1,
            "pending_code_fixes": [finding.model_dump()],
            "pending_test_fixes": [],
            "code_changed_in_fix": False,
        }

    deps.progress(f"executor ({deps.executor.name}): running tests")
    spec = ExecutionSpec(packages=selection.install, timeout_seconds=deps.test_timeout_seconds)
    result: ExecutionResult = await in_thread(deps.executor.run_tests, files, spec)
    rounds = list(state.get("test_rounds", []))
    rounds.append({"round": len(rounds) + 1, "result": result.model_dump(), "triage": None})
    deps.progress(
        f"tests {len(rounds)}: {result.status} (passed {result.passed}, failed "
        f"{result.failed}, errors {result.errors}, {result.duration_ms / 1000:.1f}s)"
    )
    update: dict[str, Any] = {"test_rounds": rounds, "pending_code_fixes": []}
    if result.status == "PASSED":
        update["status"] = "TESTS_PASSED"
    elif result.status == "NOT_EXECUTED":
        update |= {"status": "NOT_EXECUTED", "stop_reason": result.detail}
    elif result.status == "ERROR":
        update |= {"status": "ERROR", "stop_reason": f"test run failed: {result.detail}"}
    elif fix_rounds >= deps.max_fix_rounds:
        update |= {
            "status": "FAILED_TESTS",
            "stop_reason": f"{len(result.failures)} failing test(s) after "
            f"{fix_rounds} fix round(s)",
        }
    return update


@guard("test")
async def triage(state: RunState, runtime: Runtime[WorkflowDeps]) -> dict[str, Any]:
    deps = runtime.context
    deps.progress("tester: triaging failures")
    app_files, test_files = split_files(await read_all(deps.fs, state["workspace"]))
    rounds = [dict(r) for r in state["test_rounds"]]
    result = ExecutionResult.model_validate(rounds[-1]["result"])
    call = await in_thread(deps.tester.triage, plan_of(state), app_files, test_files, result)
    update: dict[str, Any] = spend(state, deps, call)
    rounds[-1]["triage"] = call.data.model_dump()
    update["test_rounds"] = rounds

    items = call.data.items
    code = [i for i in items if i.cause == "bad_code"]
    tests = [i for i in items if i.cause == "bad_test"]
    deps.progress(
        f"triage: bad_code {len(code)}, bad_test {len(tests)}, "
        f"environment {len(items) - len(code) - len(tests)}"
    )
    if not code and not tests:
        return update | {
            "status": "FAILED_TESTS",
            "stop_reason": f"environment problem: {call.data.summary}",
        }
    findings = [
        Finding(
            source="tests",
            file=i.file,
            line=0,
            severity="high",
            category="bug",
            message=f"{i.test} fails: {i.reason}",
            suggested_fix=i.suggested_fix,
        ).model_dump()
        for i in code
    ]
    return update | {
        "fix_rounds": state.get("fix_rounds", 0) + 1,
        "pending_code_fixes": findings,
        "pending_test_fixes": [i.model_dump() for i in tests],
        "code_changed_in_fix": False,
    }


@guard("test")
async def fix_code(state: RunState, runtime: Runtime[WorkflowDeps]) -> dict[str, Any]:
    deps = runtime.context
    deps.progress(f"developer: fix round {state.get('fix_rounds', 0)}")
    app_files, _ = split_files(await read_all(deps.fs, state["workspace"]))
    findings = [Finding.model_validate(f) for f in state["pending_code_fixes"]]
    call = await in_thread(deps.developer.revise, plan_of(state), app_files, findings)
    update = spend(state, deps, call)
    changed = await write_changes(deps.fs, state["workspace"], call.data)
    deps.progress(f"updated {', '.join(changed)}")
    return update | {"pending_code_fixes": [], "code_changed_in_fix": True}


@guard("test")
async def fix_tests(state: RunState, runtime: Runtime[WorkflowDeps]) -> dict[str, Any]:
    deps = runtime.context
    deps.progress(f"tester: fixing tests, round {state.get('fix_rounds', 0)}")
    app_files, test_files = split_files(await read_all(deps.fs, state["workspace"]))
    items = [TriageItem.model_validate(i) for i in state["pending_test_fixes"]]
    call = await in_thread(deps.tester.fix_tests, plan_of(state), app_files, test_files, items)
    update = spend(state, deps, call)
    await write_changes(deps.fs, state["workspace"], call.data)
    return update | {"pending_test_fixes": []}
