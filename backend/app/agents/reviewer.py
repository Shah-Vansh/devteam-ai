"""Reviewer agent: files + plan + static analysis -> ReviewReport.

The Reviewer reads the workspace through `ReadOnlyFilesystem`, the agent view of the
Filesystem MCP server, so it has no way to change the code it is judging.
The verdict is computed from the findings (see `app/schemas/review.py`), not chosen by
the model.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

import anyio.to_thread

from app.agents.common import (
    AgentCall,
    files_block,
    generate_checked,
    outlines_block,
    size_batches,
)
from app.agents.developer import plan_block
from app.analysis.static import StaticReport, analyze
from app.llm.base import LLMClient, LLMUsage
from app.mcp_clients.filesystem import ReadOnlyFilesystem
from app.schemas.plan import ProjectPlan
from app.schemas.review import Finding, ReviewOutput, ReviewReport

PROMPT_FILE = Path(__file__).parent / "prompts" / "reviewer_system.md"


@dataclass
class ReviewResult:
    report: ReviewReport
    static: StaticReport
    usages: list[LLMUsage] = field(default_factory=list)


def static_block(static: StaticReport) -> str:
    lines = ["<static_analysis>"]
    if not static.findings:
        lines.append("No findings.")
    for f in static.findings:
        lines.append(f"- {f.source} {f.rule} {f.file}:{f.line} [{f.severity}] {f.message}")
    for tool, reason in static.tools_failed.items():
        lines.append(f"- {tool} could not run: {reason}")
    lines.append("</static_analysis>")
    return "\n".join(lines)


class Reviewer:
    agent_name = "reviewer"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._system_prompt = PROMPT_FILE.read_text(encoding="utf-8")

    async def review(
        self, *, workspace: str, plan: ProjectPlan, fs: ReadOnlyFilesystem, round: int = 1
    ) -> ReviewResult:
        files = {
            path: await fs.read_file(workspace, path) for path in await fs.list_files(workspace)
        }
        static = await anyio.to_thread.run_sync(analyze, files)

        findings = [*static.findings]
        summaries: list[str] = []
        usages: list[LLMUsage] = []
        # Large projects are reviewed in parts; each part also sees outlines of the rest.
        for batch in size_batches(sorted(files), files):
            call = await anyio.to_thread.run_sync(
                partial(self._ask_model, plan, files, batch, static)
            )
            usages.extend(call.usages)
            summaries.append(call.data.summary.strip())
            findings += [Finding(source="reviewer", **f.model_dump()) for f in call.data.findings]

        summary = " ".join(s for s in summaries if s)
        if static.tools_failed:
            summary += f" (static tools that could not run: {', '.join(static.tools_failed)})"
        report = ReviewReport(round=round, summary=summary, findings=findings)
        return ReviewResult(report=report, static=static, usages=usages)

    def _ask_model(
        self, plan: ProjectPlan, files: dict[str, str], batch: list[str], static: StaticReport
    ) -> AgentCall[ReviewOutput]:
        in_batch = set(batch)
        shown = {p: files[p] for p in batch}
        others = {p: c for p, c in files.items() if p not in in_batch}
        batch_static = StaticReport(
            findings=[f for f in static.findings if f.file in in_batch],
            tools_run=static.tools_run,
            tools_failed=static.tools_failed,
        )
        scope = (
            "Review the files shown in full. Outlines of the other project files are given "
            "so you can check how the files fit together; report problems in outlined files "
            "only when the outline itself shows them."
            if others
            else "Review the files against the plan."
        )
        user = "\n\n".join(
            part
            for part in (
                plan_block(plan),
                files_block(shown, numbered=True),
                outlines_block(others),
                static_block(batch_static),
                scope,
            )
            if part
        )

        def check(output: ReviewOutput) -> list[str]:
            # Findings about outlined files are allowed (an outline can show a real
            # problem, such as a route order), but a file must exist in the project.
            unknown = sorted({f.file for f in output.findings} - set(files))
            if unknown:
                return [f"findings cite files that do not exist: {', '.join(unknown)}"]
            return []

        return generate_checked(
            self._llm,
            system=self._system_prompt,
            user=user,
            schema=ReviewOutput,
            agent=self.agent_name,
            check=check,
        )


def sort_findings(findings: Sequence[Finding]) -> list[Finding]:
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(findings, key=lambda f: (order[f.severity], f.file, f.line))
