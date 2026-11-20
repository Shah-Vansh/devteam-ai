"""Copy a run's workflow state into the database tables.

The LangGraph checkpoint is the source of truth while a run is active; these tables are
the queryable record the API and dashboard read. Every function is idempotent (it adds
only what is missing), so it is safe to call after every node, on pause and at the end.
"""

import hashlib
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Approval,
    GeneratedFile,
    LLMCall,
    ReviewFinding,
    ReviewReport,
    Run,
    TestCase,
    TestRun,
    utcnow,
)
from app.workflow.state import TERMINAL


def run_status(state: dict[str, Any], pause: dict[str, Any] | None) -> str:
    if pause is not None:
        return "PAUSED"
    return state.get("status") or "RUNNING"


def sync_run(session: Session, run: Run, state: dict[str, Any], pause: dict | None) -> None:
    status = run_status(state, pause)
    run.status = status
    run.workspace = state.get("workspace") or run.workspace
    run.model = state.get("model") or run.model
    run.review_rounds = state.get("review_rounds", 0)
    run.fix_rounds = state.get("fix_rounds", 0)
    run.llm_calls = state.get("llm_calls", 0)
    run.input_tokens = state.get("input_tokens", 0)
    run.output_tokens = state.get("output_tokens", 0)
    if state.get("reports"):
        run.review_status = state["reports"][-1]["verdict"]
    if state.get("test_rounds"):
        run.test_status = state["test_rounds"][-1]["result"]["status"]
    if state.get("commit"):
        run.commit_sha = state["commit"]["commit"]
    run.error = state.get("stop_reason") or None
    if status in TERMINAL and run.finished_at is None:
        run.finished_at = utcnow()

    _sync_reviews(session, run, state.get("reports", []))
    _sync_tests(session, run, state.get("test_rounds", []))
    _sync_llm_calls(session, run, state.get("llm_log", []))
    if state.get("commit_token_hash"):
        _store_token_hash(session, run, state["commit_token_hash"])


def _sync_reviews(session: Session, run: Run, reports: list[dict[str, Any]]) -> None:
    stored = set(session.scalars(select(ReviewReport.round).where(ReviewReport.run_id == run.id)))
    for report in reports:
        if report["round"] in stored:
            continue
        row = ReviewReport(
            run_id=run.id,
            round=report["round"],
            verdict=report["verdict"],
            summary=report.get("summary", ""),
        )
        row.findings = [
            ReviewFinding(
                file=f["file"],
                line=f.get("line", 0),
                severity=f["severity"],
                category=f["category"],
                source=f["source"],
                rule=f.get("rule", ""),
                message=f["message"],
                suggested_fix=f.get("suggested_fix", ""),
            )
            for f in report.get("findings", [])
        ]
        session.add(row)


def _sync_tests(session: Session, run: Run, rounds: list[dict[str, Any]]) -> None:
    stored = {t.round: t for t in session.scalars(select(TestRun).where(TestRun.run_id == run.id))}
    for test_round in rounds:
        row = stored.get(test_round["round"])
        if row is not None:
            if row.triage is None and test_round.get("triage"):
                row.triage = test_round["triage"]  # triage arrives one node later
            continue
        result = test_round["result"]
        row = TestRun(
            run_id=run.id,
            round=test_round["round"],
            executor=result["executor"],
            status=result["status"],
            passed=result["passed"],
            failed=result["failed"],
            errors=result["errors"],
            skipped=result["skipped"],
            duration_ms=result["duration_ms"],
            detail=result.get("detail", ""),
            triage=test_round.get("triage"),
        )
        row.cases = [
            TestCase(name=c["name"], outcome=c["outcome"], message=c.get("message", ""))
            for c in result.get("cases", [])
        ]
        session.add(row)


def _sync_llm_calls(session: Session, run: Run, log: list[dict[str, Any]]) -> None:
    count = session.scalar(select(func.count()).where(LLMCall.run_id == run.id)) or 0
    for entry in log[count:]:
        session.add(LLMCall(run_id=run.id, **entry))


def _store_token_hash(session: Session, run: Run, token_hash: str) -> None:
    approval = session.scalars(
        select(Approval)
        .where(Approval.run_id == run.id, Approval.kind == "commit", Approval.status == "approved")
        .order_by(Approval.created_at.desc())
    ).first()
    if approval is not None and approval.token_hash is None:
        approval.token_hash = token_hash


def ensure_approval(session: Session, run: Run, pause: dict[str, Any]) -> Approval:
    """The pending approval for the current pause, created once."""
    pending = session.scalars(
        select(Approval).where(
            Approval.run_id == run.id, Approval.status == "pending", Approval.kind == pause["kind"]
        )
    ).first()
    if pending is None:
        pending = Approval(run_id=run.id, kind=pause["kind"], payload=pause)
        session.add(pending)
        session.flush()  # assigns nothing new, but makes the row visible in this session
    return pending


def sync_files(session: Session, run: Run, files: dict[str, str]) -> None:
    """Record path, SHA-256 and size of each file; a new version row when content changed.
    File contents stay on disk, never in the database."""
    latest: dict[str, GeneratedFile] = {}
    for row in session.scalars(
        select(GeneratedFile).where(GeneratedFile.run_id == run.id).order_by(GeneratedFile.id)
    ):
        latest[row.path] = row
    for path, content in files.items():
        data = content.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        previous = latest.get(path)
        if previous is not None and previous.sha256 == digest:
            continue
        session.add(
            GeneratedFile(
                run_id=run.id,
                path=path,
                sha256=digest,
                size_bytes=len(data),
                version=previous.version + 1 if previous else 1,
            )
        )
