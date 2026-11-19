"""Helpers shared by the agents."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.analysis.outline import outline_file
from app.llm.base import LLMClient, LLMUsage

# Roughly 2,000 tokens of full source per request. Together with the plan, outlines and
# the answer, this stays inside an 8,000 tokens-per-minute free-tier limit.
FULL_TEXT_CHAR_BUDGET = 8000


class AgentOutputError(Exception):
    """The model's answer was valid JSON but still broke a rule after one corrective retry."""

    def __init__(self, agent: str, problems: Sequence[str]) -> None:
        super().__init__(f"{agent} output rejected: " + "; ".join(problems))
        self.problems = list(problems)


@dataclass
class AgentCall[T: BaseModel]:
    data: T
    usages: list[LLMUsage] = field(default_factory=list)


def generate_checked[T: BaseModel](
    llm: LLMClient,
    *,
    system: str,
    user: str,
    schema: type[T],
    agent: str,
    check: Callable[[T], list[str]],
) -> AgentCall[T]:
    """Ask once; if `check` finds problems the schema cannot express (for example
    "you skipped a planned file"), ask once more and tell the model exactly what was wrong.
    Pydantic and transport retries already happen inside the LLM client."""
    result = llm.generate_structured(system=system, user=user, schema=schema, agent=agent)
    usages = [result.usage]
    problems = check(result.data)
    if problems:
        feedback = "\n".join(f"- {p}" for p in problems)
        retry_user = (
            f"{user}\n\n<problems_with_previous_answer>\n{feedback}\n"
            "</problems_with_previous_answer>\nReturn a complete, corrected answer."
        )
        result = llm.generate_structured(system=system, user=retry_user, schema=schema, agent=agent)
        usages.append(result.usage)
        problems = check(result.data)
        if problems:
            raise AgentOutputError(agent, problems)
    return AgentCall(data=result.data, usages=usages)


def files_block(files: Mapping[str, str], *, numbered: bool = False) -> str:
    """Files as tagged data. Line numbers help the Reviewer cite exact lines."""
    parts = ["<files>"]
    for path in sorted(files):
        content = files[path]
        if numbered:
            content = "\n".join(
                f"{i:>4} | {line}" for i, line in enumerate(content.splitlines(), 1)
            )
        parts.append(f'<file path="{path}">\n{content}\n</file>')
    parts.append("</files>")
    return "\n".join(parts)


def outlines_block(files: Mapping[str, str]) -> str:
    """Other project files as AST outlines (signatures, routes, fields; no bodies)."""
    if not files:
        return ""
    parts = ["<outlines>"]
    for path in sorted(files):
        parts.append(f'<outline path="{path}">\n{outline_file(path, files[path])}\n</outline>')
    parts.append("</outlines>")
    return "\n".join(parts)


def size_batches(
    paths: Sequence[str], files: Mapping[str, str], budget: int = FULL_TEXT_CHAR_BUDGET
) -> list[list[str]]:
    """Group paths, in order, so each group's full text stays under `budget` characters.
    A single file larger than the budget gets a group of its own."""
    batches: list[list[str]] = []
    current: list[str] = []
    size = 0
    for path in paths:
        length = len(files[path])
        if current and size + length > budget:
            batches.append(current)
            current, size = [], 0
        current.append(path)
        size += length
    if current:
        batches.append(current)
    return batches


def context_block(files: Mapping[str, str], budget: int = FULL_TEXT_CHAR_BUDGET) -> str:
    """As much full text as fits in `budget` (smallest files first, which keeps the most
    files whole), and outlines for the rest."""
    full: dict[str, str] = {}
    used = 0
    for path in sorted(files, key=lambda p: len(files[p])):
        if used + len(files[path]) > budget:
            break
        full[path] = files[path]
        used += len(files[path])
    rest = {p: c for p, c in files.items() if p not in full}
    return "\n\n".join(
        part for part in (files_block(full, numbered=False), outlines_block(rest)) if part
    )
