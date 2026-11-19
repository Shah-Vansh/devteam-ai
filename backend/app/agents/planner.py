"""Planner agent: requirement (+ optional clarifications) -> validated ProjectPlan."""

from dataclasses import dataclass
from pathlib import Path

from app.execution.packages import packages_rule
from app.llm.base import LLMClient, LLMUsage
from app.schemas.plan import Clarification, ProjectPlan

PROMPT_FILE = Path(__file__).parent / "prompts" / "planner_system.md"
MAX_REQUIREMENT_CHARS = 4000


class PlannerInputError(ValueError):
    """The requirement is empty or too long; no LLM call is made."""


@dataclass(frozen=True)
class PlannerResult:
    plan: ProjectPlan
    usage: LLMUsage
    attempts: int


class Planner:
    agent_name = "planner"

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._system_prompt = PROMPT_FILE.read_text(encoding="utf-8") + packages_rule()

    def plan(
        self, requirement: str, clarifications: list[Clarification] | None = None
    ) -> PlannerResult:
        requirement = requirement.strip()
        if not requirement:
            raise PlannerInputError("requirement is empty")
        if len(requirement) > MAX_REQUIREMENT_CHARS:
            raise PlannerInputError(
                f"requirement is {len(requirement)} characters; maximum is {MAX_REQUIREMENT_CHARS}"
            )

        result = self._llm.generate_structured(
            system=self._system_prompt,
            user=self.build_user_message(requirement, clarifications or []),
            schema=ProjectPlan,
            agent=self.agent_name,
        )
        return PlannerResult(plan=result.data, usage=result.usage, attempts=result.attempts)

    @staticmethod
    def build_user_message(requirement: str, clarifications: list[Clarification]) -> str:
        """User data goes inside clear tags so the model treats it as data, not instructions."""
        parts = ["<requirement>", requirement, "</requirement>"]
        if clarifications:
            parts.append("<clarifications>")
            for item in clarifications:
                parts.append(f"Q: {item.question}\nA: {item.answer}")
            parts.append("</clarifications>")
        return "\n".join(parts)
