"""Request and response models of the HTTP API (docs/API_DESIGN.md)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    requirement: str = Field(min_length=1, max_length=4000)


class ProjectOut(ORM):
    id: str
    name: str
    requirement: str
    created_at: datetime


class RunSummary(ORM):
    id: str
    status: str
    started_at: datetime
    finished_at: datetime | None


class ProjectDetail(ProjectOut):
    runs: list[RunSummary]


class ApprovalOut(ORM):
    id: str
    run_id: str
    kind: Literal["clarify", "execute", "commit"]
    status: Literal["pending", "approved", "rejected", "cancelled"]
    payload: dict[str, Any]
    answer: dict[str, Any] | None
    created_at: datetime
    decided_at: datetime | None
    # token_hash is deliberately not exposed


class RunOut(ORM):
    id: str
    project_id: str
    status: str
    current_step: str | None
    review_status: str | None
    test_status: str | None
    review_rounds: int
    fix_rounds: int
    workspace: str | None
    model: str | None
    llm_calls: int
    input_tokens: int
    output_tokens: int
    commit_sha: str | None
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    pending_approval: ApprovalOut | None = None


class RunStarted(BaseModel):
    run_id: str
    status: str


class CancelAccepted(BaseModel):
    run_id: str
    status: str


class FileEntry(BaseModel):
    path: str
    size_bytes: int


class FileContent(BaseModel):
    path: str
    content: str


class FindingOut(ORM):
    file: str
    line: int
    severity: str
    category: str
    source: str
    rule: str
    message: str
    suggested_fix: str


class ReviewOut(ORM):
    round: int
    verdict: str
    summary: str
    findings: list[FindingOut]


class TestCaseOut(ORM):
    __test__ = False
    name: str
    outcome: str
    message: str


class TestRunOut(ORM):
    __test__ = False
    round: int
    executor: str
    status: str
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_ms: int
    detail: str
    triage: dict[str, Any] | None
    cases: list[TestCaseOut]


class StepOut(ORM):
    agent: str
    round: int
    status: str
    summary: str
    finished_at: datetime | None


class AgentUsage(BaseModel):
    agent: str
    calls: int
    input_tokens: int
    output_tokens: int


class Report(BaseModel):
    run: RunOut
    steps: list[StepOut]
    final_review: ReviewOut | None
    final_tests: TestRunOut | None
    files: list[FileEntry]
    usage_by_agent: list[AgentUsage]


class Decision(BaseModel):
    decision: Literal["approve", "reject", "cancel"]
    answers: list[str] = Field(default_factory=list, max_length=10)
    answer: str | None = Field(default=None, max_length=2000)  # one answer, as in the docs
    message: str | None = Field(default=None, max_length=2000)  # commit message override


class GitFile(BaseModel):
    status: str
    path: str


class GitCommit(BaseModel):
    commit: str
    author: str
    date: str
    subject: str


class GitInfo(BaseModel):
    initialized: bool
    branch: str | None
    clean: bool | None
    files: list[GitFile]
    commits: list[GitCommit]


class Health(BaseModel):
    status: Literal["ok"]
    executor: str
    model: str | None
    llm_configured: bool
    llm_error: str | None
    git_available: bool
