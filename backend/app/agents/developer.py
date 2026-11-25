"""Developer agent: plan -> code, and code + findings -> revised code.

The Developer returns file contents only. Workflow code writes them through the
Filesystem MCP server (ADR 0004), so a prompt-injected model still cannot write
anywhere except the planned workspace paths, which the schema has already validated.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path

from app.agents.common import (
    AgentCall,
    files_block,
    generate_checked,
    outlines_block,
    size_batches,
)
from app.execution.packages import packages_rule
from app.llm.base import LLMClient
from app.schemas.code import CodeChanges
from app.schemas.plan import ProjectPlan
from app.schemas.review import Finding

PROMPT_FILE = Path(__file__).parent / "prompts" / "developer_system.md"
FILES_PER_CALL = 4


class DeveloperInputError(ValueError):
    """Called with nothing to do; no LLM call is made."""


def plan_block(plan: ProjectPlan) -> str:
    # Open questions were answered or turned into assumptions; they would only distract.
    # Compact JSON: the plan is in every request, and indentation cost 800-1,000 characters
    # of a hard project's plan (found live, benchmark b08 and b09; see REVIEW_CHAR_BUDGET).
    return "<plan>\n" + plan.model_dump_json(exclude={"open_questions"}) + "\n</plan>"


def findings_block(findings: Sequence[Finding]) -> str:
    lines = ["<findings>"]
    for f in findings:
        where = f"{f.file} line {f.line}" if f.line else f.file
        lines.append(f"- [{f.severity}][{f.category}] {where}: {f.message}")
        lines.append(f"  Fix: {f.suggested_fix}")
    lines.append("</findings>")
    return "\n".join(lines)


def file_batches(plan: ProjectPlan, size: int = FILES_PER_CALL) -> list[list[str]]:
    """Planned files in task order (files no task mentions go last), chunked."""
    ordered: list[str] = []
    for task in sorted(plan.tasks, key=lambda t: t.id):
        ordered += [p for p in task.files if p not in ordered]
    ordered += [f.path for f in plan.files if f.path not in ordered]
    return [ordered[i : i + size] for i in range(0, len(ordered), size)]


class Developer:
    agent_name = "developer"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._system_prompt = PROMPT_FILE.read_text(encoding="utf-8") + packages_rule()

    def generate(self, plan: ProjectPlan) -> AgentCall[CodeChanges]:
        """Write every planned file, in batches of at most FILES_PER_CALL.

        One answer containing a whole multi-file project as JSON strings is long and
        fragile: in a live run Groq failed to produce valid JSON for 9 files twice in a
        row. Small batches in task order keep each answer short, and each batch sees the
        files already written, so imports and names stay consistent.
        """
        written: dict[str, str] = {}
        usages = []
        notes = []
        for batch in file_batches(plan):
            call = self._generate_batch(plan, batch, written)
            # Keep only this batch's files. A model that re-sends earlier planned files
            # (seen live with a smaller model) must not overwrite them.
            written.update({p: c for p, c in call.data.as_dict().items() if p in batch})
            usages.extend(call.usages)
            if call.data.notes.strip():
                notes.append(call.data.notes.strip())
        changes = CodeChanges.model_validate(
            {
                "files": [
                    {"path": p, "content": c, "reason": "planned file"} for p, c in written.items()
                ],
                "notes": "\n".join(notes),
            }
        )
        return AgentCall(data=changes, usages=usages)

    def _generate_batch(
        self, plan: ProjectPlan, batch: list[str], written: Mapping[str, str]
    ) -> AgentCall[CodeChanges]:
        wanted = set(batch)
        planned = {f.path for f in plan.files}
        # Outlines (imports, signatures, routes, fields) of earlier batches are enough to
        # stay consistent with them and much smaller than their full text.
        context = f"\n\nFiles already written:\n{outlines_block(written)}" if written else ""
        user = (
            f"{plan_block(plan)}{context}\n\nWrite exactly these files now, and no others: "
            f"{', '.join(batch)}. Remaining planned files will be written later, following the "
            "plan; you may import from them as the plan describes."
        )

        def check(changes: CodeChanges) -> list[str]:
            returned = {f.path for f in changes.files}
            problems = []
            if missing := sorted(wanted - returned):
                problems.append(f"these requested files are missing: {', '.join(missing)}")
            if extra := sorted(returned - planned):
                problems.append(f"these files are not in the plan: {', '.join(extra)}")
            return problems

        return generate_checked(
            self._llm,
            system=self._system_prompt,
            user=user,
            schema=CodeChanges,
            agent=self.agent_name,
            check=check,
        )

    def revise(
        self, plan: ProjectPlan, files: Mapping[str, str], findings: Sequence[Finding]
    ) -> AgentCall[CodeChanges]:
        """Fix findings. Only files that have findings are sent in full (in size-limited
        batches); the rest of the project is sent as outlines."""
        if not findings:
            raise DeveloperInputError("revise needs at least one finding")
        current = dict(files)
        # requirements.txt may be created by a fix if it is missing altogether
        targets = sorted(
            {f.file for f in findings if f.file in current or f.file == "requirements.txt"}
        )
        if not targets:
            raise DeveloperInputError("findings do not refer to any existing file")
        for path in targets:
            current.setdefault(path, "")  # a file to create starts empty

        changed: dict[str, str] = {}
        usages = []
        for batch in size_batches(targets, current):
            batch_findings = [f for f in findings if f.file in batch]
            call = self._revise_batch(plan, current, batch, batch_findings)
            usages.extend(call.usages)
            for change in call.data.files:
                current[change.path] = changed[change.path] = change.content
        changes = CodeChanges.model_validate(
            {
                "files": [
                    {"path": p, "content": c, "reason": "review fix"} for p, c in changed.items()
                ],
                "notes": "",
            }
        )
        return AgentCall(data=changes, usages=usages)

    def _revise_batch(
        self,
        plan: ProjectPlan,
        files: Mapping[str, str],
        batch: list[str],
        findings: Sequence[Finding],
    ) -> AgentCall[CodeChanges]:
        allowed = set(batch)
        others = {p: c for p, c in files.items() if p not in allowed}
        user = "\n\n".join(
            part
            for part in (
                plan_block(plan),
                files_block({p: files.get(p, "") for p in batch}),
                outlines_block(others),
                findings_block(findings),
                "Fix every finding above. Return only the files you change, chosen from the "
                f"files shown in full ({', '.join(batch)}), each with its full new content. "
                "Keep everything else working and compatible with the outlined files.",
            )
            if part
        )

        def check(changes: CodeChanges) -> list[str]:
            if not changes.files:
                return [
                    "you returned no files; every finding listed must be fixed by changing "
                    f"at least one of: {', '.join(batch)}"
                ]
            problems = []
            if outside := sorted({f.path for f in changes.files} - allowed):
                problems.append(
                    f"only these files may be changed now: {', '.join(batch)}; "
                    f"not {', '.join(outside)}"
                )
            if all(files.get(f.path) == f.content for f in changes.files):
                problems.append("none of the returned files differ from the current files")
            return problems

        return generate_checked(
            self._llm,
            system=self._system_prompt,
            user=user,
            schema=CodeChanges,
            agent=self.agent_name,
            check=check,
        )
