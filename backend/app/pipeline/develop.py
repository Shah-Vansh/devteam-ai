"""Develop-and-review loop: plan -> files on disk -> review -> revise, bounded.

This is plain async code for now. Phase 5 replaces the loop with a LangGraph graph that
adds checkpoints and human pauses, but keeps these same steps and limits:

    generate -> write -> review --pass--> REVIEW_PASSED
                           |
                     changes_needed and review_rounds < max  -> revise -> write -> review
                     changes_needed and review_rounds == max -> FAILED_REVIEW

Writes go through the full `FilesystemClient`; the Reviewer only gets `read_only()`.
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Literal

import anyio.to_thread

from app.agents.common import AgentOutputError
from app.agents.developer import Developer
from app.agents.reviewer import Reviewer
from app.llm.base import LLMUsage
from app.mcp_clients.filesystem import FilesystemClient, FilesystemToolError
from app.schemas.code import CodeChanges
from app.schemas.plan import ProjectPlan
from app.schemas.review import ReviewReport

ReviewStatus = Literal["REVIEW_PASSED", "FAILED_REVIEW"]
Progress = Callable[[str], None]


class LLMBudgetExceeded(Exception):
    """The run would need more LLM calls than MAX_LLM_CALLS_PER_RUN allows."""


@dataclass
class DevelopResult:
    workspace: str
    status: ReviewStatus
    reports: list[ReviewReport]
    review_rounds: int  # revisions requested by a review
    files: list[str]
    usages: list[LLMUsage] = field(default_factory=list)
    stop_reason: str = ""

    @property
    def final_report(self) -> ReviewReport:
        return self.reports[-1]

    @property
    def llm_calls(self) -> int:
        return len(self.usages)


def new_workspace_name(project_name: str) -> str:
    """Unique folder per run: `<project>-<6 hex chars>`, at most 64 characters."""
    base = project_name[:50].strip("-") or "project"
    return f"{base}-{secrets.token_hex(3)}"


async def write_changes(fs: FilesystemClient, workspace: str, changes: CodeChanges) -> list[str]:
    """Create new files, update existing ones. The workspace is created by the first write."""
    try:
        existing = set(await fs.list_files(workspace))
    except FilesystemToolError as exc:
        if exc.code != "WORKSPACE_NOT_FOUND":
            raise
        existing = set()
    for change in changes.files:
        if change.path in existing:
            await fs.update_file(workspace, change.path, change.content)
        else:
            await fs.create_file(workspace, change.path, change.content)
    return [c.path for c in changes.files]


async def develop_and_review(
    plan: ProjectPlan,
    *,
    workspace: str,
    developer: Developer,
    reviewer: Reviewer,
    fs: FilesystemClient,
    max_review_rounds: int = 2,
    max_llm_calls: int = 40,
    progress: Progress = lambda _msg: None,
    on_report: Callable[[ReviewReport], None] = lambda _report: None,
) -> DevelopResult:
    usages: list[LLMUsage] = []

    def spend(new: list[LLMUsage]) -> None:
        usages.extend(new)
        if len(usages) > max_llm_calls:
            raise LLMBudgetExceeded(f"used {len(usages)} LLM calls; limit is {max_llm_calls}")

    progress("developer: writing files")
    generated = await anyio.to_thread.run_sync(developer.generate, plan)
    spend(generated.usages)
    written = await write_changes(fs, workspace, generated.data)
    progress(f"wrote {len(written)} files")

    reports: list[ReviewReport] = []
    review_rounds = 0
    stop_reason = ""
    while True:
        progress(f"reviewer: round {len(reports) + 1}")
        result = await reviewer.review(
            workspace=workspace, plan=plan, fs=fs.read_only(), round=len(reports) + 1
        )
        spend(result.usages)
        report = result.report
        reports.append(report)
        on_report(report)
        counts = report.counts()
        progress(
            f"review {report.round}: {report.verdict} "
            f"(high {counts['high']}, medium {counts['medium']}, low {counts['low']})"
        )

        if report.verdict == "pass":
            status: ReviewStatus = "REVIEW_PASSED"
            break
        if review_rounds >= max_review_rounds:
            status = "FAILED_REVIEW"
            stop_reason = f"high-severity findings remain after {review_rounds} revision(s)"
            break

        review_rounds += 1
        progress(f"developer: revision {review_rounds} ({len(report.to_fix)} findings to fix)")
        current = {p: await fs.read_file(workspace, p) for p in await fs.list_files(workspace)}
        try:
            revised = await anyio.to_thread.run_sync(
                partial(developer.revise, plan, current, report.to_fix)
            )
        except AgentOutputError as exc:
            # The Developer could not produce a usable fix (for example it returned no
            # changes twice). Reviewing the same code again would not help.
            status, stop_reason = "FAILED_REVIEW", f"revision {review_rounds} failed: {exc}"
            progress(stop_reason)
            break
        spend(revised.usages)
        changed = await write_changes(fs, workspace, revised.data)
        progress(f"updated {', '.join(changed)}")

    return DevelopResult(
        workspace=workspace,
        status=status,
        reports=reports,
        review_rounds=review_rounds,
        files=await fs.list_files(workspace),
        usages=usages,
        stop_reason=stop_reason,
    )
