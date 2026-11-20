"""The run as a LangGraph StateGraph.

    plan -> clarify? -> develop -> review -> (revise -> review)* -> write_tests -> approve
    -> run_tests -> PASSED: prepare/approve_commit -> commit -> SUCCESS (declined: NOT_COMMITTED)
                 -> FAILED: triage -> fix_code -> fix_tests? -> review -> run_tests
                                   -> fix_tests -> run_tests

Routers only read the state. Every router sends a terminal status straight to END, so a
node that fails or hits a limit ends the run in a defined state. `clarify`, `approve`
and `approve_commit` pause with `interrupt()`; the SQLite checkpointer lets another
process resume them.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from app.workflow import nodes
from app.workflow.state import TERMINAL, RunState, WorkflowDeps

# Longest legal path: plan, clarify, plan, develop, 3 reviews and 2 revisions, tests,
# approval, and per fix round run/triage/fix code/fix tests/review(+revisions). Generous.
RECURSION_LIMIT = 120


def _ended(state: RunState) -> bool:
    return state.get("status") in TERMINAL


def after_plan(state: RunState) -> str:
    if _ended(state):
        return END
    return "develop" if state.get("clarified") or not state["plan"]["open_questions"] else "clarify"


def after_clarify(state: RunState) -> str:
    if _ended(state):
        return END
    return "plan" if state.get("plan") is None else "develop"


def after_develop(state: RunState) -> str:
    return END if _ended(state) else "review"


def after_review(state: RunState) -> str:
    if _ended(state):
        return END
    if state["reports"][-1]["verdict"] == "changes_needed":
        return "revise"
    return "run_tests" if state.get("tests_written") else "write_tests"


def after_revise(state: RunState) -> str:
    return END if _ended(state) else "review"


def after_write_tests(state: RunState) -> str:
    return END if _ended(state) else "approve"


def after_approve(state: RunState) -> str:
    return END if _ended(state) else "run_tests"


def after_run_tests(state: RunState) -> str:
    if _ended(state):
        return END
    if state.get("tests_passed"):
        return "prepare_commit"
    return "fix_code" if state.get("pending_code_fixes") else "triage"


def after_prepare_commit(state: RunState) -> str:
    return END if _ended(state) else "approve_commit"


def after_approve_commit(state: RunState) -> str:
    return END if _ended(state) else "commit"


def after_triage(state: RunState) -> str:
    if _ended(state):
        return END
    return "fix_code" if state.get("pending_code_fixes") else "fix_tests"


def after_fix_code(state: RunState) -> str:
    if _ended(state):
        return END
    # Changed code goes back through review, as in the architecture diagram.
    return "fix_tests" if state.get("pending_test_fixes") else "review"


def after_fix_tests(state: RunState) -> str:
    if _ended(state):
        return END
    return "review" if state.get("code_changed_in_fix") else "run_tests"


ROUTES = {
    "plan": (after_plan, ["clarify", "develop", END]),
    "clarify": (after_clarify, ["plan", "develop", END]),
    "develop": (after_develop, ["review", END]),
    "review": (after_review, ["revise", "write_tests", "run_tests", END]),
    "revise": (after_revise, ["review", END]),
    "write_tests": (after_write_tests, ["approve", END]),
    "approve": (after_approve, ["run_tests", END]),
    "run_tests": (after_run_tests, ["prepare_commit", "fix_code", "triage", END]),
    "triage": (after_triage, ["fix_code", "fix_tests", END]),
    "fix_code": (after_fix_code, ["fix_tests", "review", END]),
    "fix_tests": (after_fix_tests, ["review", "run_tests", END]),
    "prepare_commit": (after_prepare_commit, ["approve_commit", END]),
    "approve_commit": (after_approve_commit, ["commit", END]),
}


def build_graph() -> StateGraph:
    graph = StateGraph(RunState, context_schema=WorkflowDeps)
    for name in ROUTES:
        graph.add_node(name, getattr(nodes, name))
    graph.add_node("commit", nodes.commit)
    graph.add_edge(START, "plan")
    for name, (router, targets) in ROUTES.items():
        graph.add_conditional_edges(name, router, targets)
    graph.add_edge("commit", END)
    return graph


@dataclass
class Step:
    """Where a run stands after `advance`: finished, or paused waiting for a human."""

    state: dict[str, Any]
    pause: dict[str, Any] | None  # the interrupt payload, e.g. {"kind": "execute", ...}

    @property
    def finished(self) -> bool:
        return self.pause is None and self.state.get("status") in TERMINAL


def run_config(run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id}, "recursion_limit": RECURSION_LIMIT}


NodeCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


async def advance(
    app: CompiledStateGraph,
    run_id: str,
    deps: WorkflowDeps,
    value: dict | Command,
    on_node: NodeCallback | None = None,
) -> Step:
    """Start a run (`value` = initial state) or resume it (`value` = Command(resume=...)),
    and run until it finishes or pauses. `on_node(name, update)` is awaited after every
    node, which is how the API records steps and streams progress."""
    async for chunk in app.astream(value, run_config(run_id), context=deps, stream_mode="updates"):
        for node, update in chunk.items():
            if node != "__interrupt__" and on_node is not None:
                await on_node(node, update or {})
    step = await current(app, run_id)
    if step is None:  # cannot happen after a run started; kept explicit, not an assert
        raise RuntimeError(f"run {run_id} has no checkpoint")
    return step


async def current(app: CompiledStateGraph, run_id: str) -> Step | None:
    """Saved state of a run, read from the checkpointer (None if unknown)."""
    snapshot = await app.aget_state(run_config(run_id))
    if not snapshot.values:
        return None
    pauses = [i.value for task in snapshot.tasks for i in task.interrupts]
    return Step(state=dict(snapshot.values), pause=pauses[0] if pauses else None)
