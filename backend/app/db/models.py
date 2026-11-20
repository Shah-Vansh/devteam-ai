"""Database tables (see docs/DATABASE_SCHEMA.md).

Findings and test cases are rows in their own tables, not JSON blobs, so they can be
queried and counted. File contents are never stored: generated files stay on disk and
the database keeps path, SHA-256 and size. Triage results and approval payloads, which
are only ever read whole, are stored as JSON.
"""

import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("prj"))
    name: Mapped[str] = mapped_column(String(100))
    requirement: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    runs: Mapped[list["Run"]] = relationship(back_populates="project", order_by="Run.started_at")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_status", "status"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # also the LangGraph thread id
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="RUNNING")
    review_status: Mapped[str | None] = mapped_column(String(20))  # pass / changes_needed
    test_status: Mapped[str | None] = mapped_column(String(20))  # PASSED / FAILED / ...
    current_step: Mapped[str | None] = mapped_column(String(40))
    review_rounds: Mapped[int] = mapped_column(Integer, default=0)
    fix_rounds: Mapped[int] = mapped_column(Integer, default=0)
    workspace: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(100))
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    error: Mapped[str | None] = mapped_column(Text)  # stop reason for non-success endings
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]

    project: Mapped[Project] = relationship(back_populates="runs")
    steps: Mapped[list["AgentStep"]] = relationship(order_by="AgentStep.id")
    files: Mapped[list["GeneratedFile"]] = relationship(order_by="GeneratedFile.path")
    reviews: Mapped[list["ReviewReport"]] = relationship(order_by="ReviewReport.round")
    test_runs: Mapped[list["TestRun"]] = relationship(order_by="TestRun.round")
    approvals: Mapped[list["Approval"]] = relationship(order_by="Approval.created_at")
    calls: Mapped[list["LLMCall"]] = relationship(order_by="LLMCall.id")


class AgentStep(Base):
    __tablename__ = "agent_steps"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    agent: Mapped[str] = mapped_column(String(40))  # graph node name
    round: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="done")
    summary: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]


class GeneratedFile(Base):
    __tablename__ = "generated_files"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    path: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)  # bumped when content changes


class ReviewReport(Base):
    __tablename__ = "review_reports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    round: Mapped[int] = mapped_column(Integer)
    verdict: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(Text, default="")

    findings: Mapped[list["ReviewFinding"]] = relationship(
        order_by="ReviewFinding.id", cascade="all, delete-orphan"
    )


class ReviewFinding(Base):
    __tablename__ = "review_findings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("review_reports.id"), index=True)
    file: Mapped[str] = mapped_column(String(200))
    line: Mapped[int] = mapped_column(Integer, default=0)
    severity: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))
    rule: Mapped[str] = mapped_column(String(40), default="")
    message: Mapped[str] = mapped_column(Text)
    suggested_fix: Mapped[str] = mapped_column(Text, default="")


class TestRun(Base):
    __tablename__ = "test_runs"
    __test__ = False  # not a pytest test class, despite the name

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    round: Mapped[int] = mapped_column(Integer)
    executor: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(Text, default="")
    triage: Mapped[dict[str, Any] | None]

    cases: Mapped[list["TestCase"]] = relationship(
        order_by="TestCase.id", cascade="all, delete-orphan"
    )


class TestCase(Base):
    __tablename__ = "test_cases"
    __test__ = False

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    test_run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    outcome: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text, default="")


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_status", "status"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("apr"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # clarify / execute / commit
    status: Mapped[str] = mapped_column(String(20), default="pending")
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)  # what the human is shown
    answer: Mapped[dict[str, Any] | None]
    token_hash: Mapped[str | None] = mapped_column(String(64))  # commit only; never the token
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    decided_at: Mapped[datetime | None]


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    agent: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
