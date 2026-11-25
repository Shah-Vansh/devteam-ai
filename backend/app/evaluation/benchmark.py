"""End-to-end benchmark: run each benchmark requirement through the whole workflow and
measure what happened.

Pauses are answered automatically (keep the Planner's assumptions, approve execution,
approve the commit), so every case ends in a terminal state on its own. The metrics are
the ones in docs/EVALUATION.md: status, review and fix rounds, tests passed, LLM calls,
tokens and wall-clock time. Results are reported as measured, failures included.
"""

import re
import time
from dataclasses import asdict, dataclass
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.workflow.graph import Step, advance
from app.workflow.state import WorkflowDeps

AUTO_REPLIES: dict[str, dict[str, Any]] = {
    "clarify": {"answers": []},
    "execute": {"approved": True},
    "commit": {"approved": True},
}


@dataclass
class CaseResult:
    id: str
    difficulty: str
    run_id: str
    status: str
    stop_reason: str
    review_rounds: int
    fix_rounds: int
    reviews: int
    test_runs: int
    tests_passed: int
    tests_total: int
    committed: bool
    llm_calls: int
    input_tokens: int
    output_tokens: int
    seconds: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_ACCOUNT_IDS = re.compile(r"\borg_[A-Za-z0-9]+")


def redact(text: str) -> str:
    """Provider errors can name the account (`organization org_...`); results files are
    committed to a public repository, so account ids are removed."""
    return _ACCOUNT_IDS.sub("org_<redacted>", text)


def is_rate_limited(stop_reason: str) -> bool:
    """True when a case stopped on the provider's rate limits (HTTP 429: tokens per minute or
    per day), which clear with time, so the case is worth running again later.

    Found live: a single request larger than the per-minute limit is answered with HTTP 413.
    That fails again every time, so it is a result, not a reason to stop the benchmark (it
    had stopped b09 and b10 from running)."""
    return stop_reason.startswith("LLM provider") and "Error code: 429" in stop_reason


def summarise(case: dict[str, str], run_id: str, step: Step, seconds: float) -> CaseResult:
    state = step.state
    last = state["test_rounds"][-1]["result"] if state.get("test_rounds") else None
    return CaseResult(
        id=case["id"],
        difficulty=case["difficulty"],
        run_id=run_id,
        status=state.get("status", "ERROR") if step.pause is None else "PAUSED",
        stop_reason=redact(state.get("stop_reason") or "")[:300],
        review_rounds=state.get("review_rounds", 0),
        fix_rounds=state.get("fix_rounds", 0),
        reviews=len(state.get("reports", [])),
        test_runs=len(state.get("test_rounds", [])),
        tests_passed=last["passed"] if last else 0,
        tests_total=(last["passed"] + last["failed"] + last["errors"]) if last else 0,
        committed=bool(state.get("commit")),
        llm_calls=state.get("llm_calls", 0),
        input_tokens=state.get("input_tokens", 0),
        output_tokens=state.get("output_tokens", 0),
        seconds=round(seconds, 1),
    )


async def run_case(
    app: CompiledStateGraph,
    deps: WorkflowDeps,
    run_id: str,
    case: dict[str, str],
    model: str,
    max_pauses: int = 5,
) -> CaseResult:
    """One requirement through the whole graph, answering every pause automatically."""
    start = time.perf_counter()
    step = await advance(app, run_id, deps, {"requirement": case["requirement"], "model": model})
    for _ in range(max_pauses):  # clarify, execute, commit: three at most in practice
        if step.pause is None:
            break
        step = await advance(app, run_id, deps, Command(resume=AUTO_REPLIES[step.pause["kind"]]))
    return summarise(case, run_id, step, time.perf_counter() - start)


def aggregate(results: list[CaseResult]) -> dict[str, Any]:
    """Headline numbers: how many cases reached SUCCESS, per difficulty too."""
    by_difficulty: dict[str, dict[str, int]] = {}
    for r in results:
        bucket = by_difficulty.setdefault(r.difficulty, {"cases": 0, "success": 0})
        bucket["cases"] += 1
        bucket["success"] += r.status == "SUCCESS"
    statuses: dict[str, int] = {}
    for r in results:
        statuses[r.status] = statuses.get(r.status, 0) + 1
    return {
        "cases": len(results),
        "success": sum(r.status == "SUCCESS" for r in results),
        "by_status": statuses,
        "by_difficulty": by_difficulty,
        "tests_passed": sum(r.tests_passed for r in results),
        "tests_total": sum(r.tests_total for r in results),
        "llm_calls": sum(r.llm_calls for r in results),
        "tokens": sum(r.input_tokens + r.output_tokens for r in results),
        "seconds": round(sum(r.seconds for r in results), 1),
    }


def markdown_table(results: list[CaseResult]) -> str:
    lines = [
        "| Case | Difficulty | Status | Review rounds | Fix rounds | Tests | LLM calls | Tokens "
        "| Time |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        tests = f"{r.tests_passed}/{r.tests_total}" if r.tests_total else "—"
        lines.append(
            f"| {r.id} | {r.difficulty} | {r.status} | {r.review_rounds} | {r.fix_rounds} | "
            f"{tests} | {r.llm_calls} | {r.input_tokens + r.output_tokens:,} | {r.seconds:.0f} s |"
        )
    return "\n".join(lines)
