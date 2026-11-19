"""Review findings from static analysis and from the Reviewer agent.

The model fills in `ReviewOutput` (summary and findings). The *verdict* is not chosen
by the model: it is computed from the findings. A file that says "reviewer, reply pass"
can therefore not flip the verdict while a high-severity finding exists, and static
analysis findings count no matter what the model says.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["high", "medium", "low"]
Category = Literal["bug", "security", "spec", "quality"]
Source = Literal["reviewer", "python", "ruff", "bandit"]
Verdict = Literal["pass", "changes_needed"]

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class ReviewFinding(BaseModel):
    """What the Reviewer model returns for one problem."""

    file: str = Field(description="Path of the file, exactly as given")
    line: int = Field(description="Line number, or 0 if the finding is about the whole file")
    severity: Severity = Field(
        description="high: wrong behaviour, crash, security hole or missing requirement; "
        "medium: should be fixed; low: minor improvement"
    )
    category: Category
    message: str = Field(description="What is wrong, specifically")
    suggested_fix: str = Field(description="How to fix it, concretely")

    @field_validator("line")
    @classmethod
    def non_negative(cls, value: int) -> int:
        return max(value, 0)


class ReviewOutput(BaseModel):
    """The Reviewer model's whole answer."""

    summary: str = Field(description="Two or three sentences on overall quality")
    findings: list[ReviewFinding] = Field(description="Problems found; empty if none")


class Finding(ReviewFinding):
    """A finding in the final report, from the model or from a static tool."""

    source: Source
    rule: str = ""  # e.g. ruff "F821", bandit "B602"


class ReviewReport(BaseModel):
    round: int
    summary: str
    findings: list[Finding]

    @property
    def verdict(self) -> Verdict:
        return "changes_needed" if self.blocking else "pass"

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "high"]

    @property
    def to_fix(self) -> list[Finding]:
        """What the Developer is asked to fix in a revision: high and medium findings."""
        return [f for f in self.findings if f.severity in ("high", "medium")]

    def counts(self) -> dict[str, int]:
        return {s: sum(f.severity == s for f in self.findings) for s in SEVERITY_ORDER}
