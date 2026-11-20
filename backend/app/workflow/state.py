"""What the workflow remembers between steps, and what a run needs but never stores.

`RunState` is checkpointed to SQLite after every node, so it holds only plain data
(dicts, lists, strings, numbers). Pydantic objects are stored as dicts and rebuilt when
a node needs them. Everything that is not data (the LLM client, the MCP connection, the
executor) lives in `WorkflowDeps`, which is passed in again on every start or resume.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from app.agents.developer import Developer
from app.agents.planner import Planner
from app.agents.reviewer import Reviewer
from app.agents.tester import Tester
from app.execution.base import CodeExecutor
from app.mcp_clients.filesystem import FilesystemClient
from app.mcp_clients.git import GitClient

RunStatus = Literal[
    "RUNNING",
    "SUCCESS",
    "NOT_COMMITTED",
    "FAILED_REVIEW",
    "FAILED_TESTS",
    "NOT_EXECUTED",
    "ERROR",
    "CANCELLED",
]
TERMINAL = frozenset(
    {
        "SUCCESS",
        "NOT_COMMITTED",
        "FAILED_REVIEW",
        "FAILED_TESTS",
        "NOT_EXECUTED",
        "ERROR",
        "CANCELLED",
    }
)


class RunState(TypedDict, total=False):
    # input
    requirement: str
    plan: dict[str, Any] | None  # ProjectPlan; may be given instead of a requirement
    model: str  # LLM model of this run, so a resume uses the same one
    # progress
    status: RunStatus
    stop_reason: str
    workspace: str
    clarifications: list[dict[str, str]]  # Clarification dicts
    clarified: bool
    review_rounds: int  # revisions requested by reviews
    fix_rounds: int  # fix rounds after failing tests
    reports: list[dict[str, Any]]  # ReviewReport dicts, with "verdict"
    tests_written: bool
    execution_approved: bool
    test_rounds: list[dict[str, Any]]  # {"round", "result", "triage"}
    pending_code_fixes: list[dict[str, Any]]  # Finding dicts for the Developer
    pending_test_fixes: list[dict[str, Any]]  # TriageItem dicts for the Tester
    code_changed_in_fix: bool
    tests_passed: bool
    approved_digest: str  # fingerprint of the files the human approved for commit
    commit_files: list[str]
    commit_message: str
    commit: dict[str, Any]  # {"commit", "branch", "files"} after SUCCESS
    commit_token_hash: str  # SHA-256 of the approval token used (never the token)
    # cost
    llm_calls: int
    input_tokens: int
    output_tokens: int
    llm_log: list[dict[str, Any]]  # one entry per LLM call: agent, model, tokens, latency


@dataclass
class WorkflowDeps:
    """Live objects and limits for one start or resume of a run (never checkpointed)."""

    planner: Planner
    developer: Developer
    reviewer: Reviewer
    tester: Tester
    executor: CodeExecutor
    fs: FilesystemClient
    git: GitClient
    max_review_rounds: int = 2
    max_fix_rounds: int = 2
    max_llm_calls: int = 40
    test_timeout_seconds: int = 120
    ask_clarifications: bool = True
    auto_approve_execution: bool = False
    auto_approve_commit: bool = False
    progress: Callable[[str], None] = field(default=lambda _msg: None)
