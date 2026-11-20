import json
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_events, get_manager, get_runtime, get_session
from app.api.schemas import (
    AgentUsage,
    ApprovalOut,
    CancelAccepted,
    Decision,
    FileContent,
    FileEntry,
    Report,
    ReviewOut,
    RunOut,
    StepOut,
    TestRunOut,
)
from app.db.models import Approval, Run
from app.mcp_clients.filesystem import FilesystemToolError
from app.services.errors import ServiceError, not_found
from app.services.events import EventBroker
from app.services.run_manager import RunManager
from app.services.runtime import Runtime
from app.workflow.state import TERMINAL

router = APIRouter(prefix="/api", tags=["runs"])
SessionDep = Annotated[Session, Depends(get_session)]
RuntimeDep = Annotated[Runtime, Depends(get_runtime)]


def load_run(session: Session, run_id: str) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise not_found("run", run_id)
    return run


def run_out(session: Session, run: Run) -> RunOut:
    out = RunOut.model_validate(run)
    pending = session.scalars(
        select(Approval).where(Approval.run_id == run.id, Approval.status == "pending")
    ).first()
    out.pending_approval = ApprovalOut.model_validate(pending) if pending else None
    return out


@router.get("/runs/{run_id}")
def get_run(run_id: str, session: SessionDep) -> RunOut:
    return run_out(session, load_run(session, run_id))


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    session: SessionDep,
    events: Annotated[EventBroker, Depends(get_events)],
    last_event_id: Annotated[int, Header()] = 0,
) -> EventSourceResponse:
    """Server-Sent Events: `log`, `step`, `approval_required`, `approval_decided`,
    `finished`. Reconnecting with Last-Event-ID resumes after that event."""
    run = run_out(session, load_run(session, run_id))

    async def stream() -> AsyncIterator[dict]:
        if not events.has_history(run_id):
            # Nothing in memory (finished before a restart, or paused across one):
            # describe the run from the database first.
            yield {"event": "status", "data": run.model_dump_json()}
            if run.status in TERMINAL or run.status == "ERROR":
                yield {"event": "finished", "data": json.dumps({"status": run.status})}
                return
            if run.pending_approval is not None:
                approval = run.pending_approval
                payload = {"approval_id": approval.id, "kind": approval.kind}
                yield {"event": "approval_required", "data": json.dumps(payload)}
        async for item in events.subscribe(run_id, after=last_event_id):
            yield {"id": str(item.id), "event": item.event, "data": json.dumps(item.data)}

    return EventSourceResponse(stream(), ping=15)


@router.get("/runs/{run_id}/files")
async def list_run_files(run_id: str, session: SessionDep, runtime: RuntimeDep) -> list[FileEntry]:
    run = load_run(session, run_id)
    if not run.workspace:
        return []
    try:
        # The API reads through the read-only view, like an agent would.
        data = await runtime.fs.read_only().call("list_files", {"workspace": run.workspace})
    except FilesystemToolError as exc:
        if exc.code == "WORKSPACE_NOT_FOUND":
            return []
        raise
    return [FileEntry(**entry) for entry in data["files"]]


@router.get("/runs/{run_id}/files/content")
async def read_run_file(
    run_id: str,
    session: SessionDep,
    runtime: RuntimeDep,
    path: Annotated[str, Query(min_length=1, max_length=200)],
) -> FileContent:
    run = load_run(session, run_id)
    if not run.workspace:
        raise ServiceError(404, "FILE_NOT_FOUND", f"run {run_id} has no files yet")
    try:
        content = await runtime.fs.read_only().read_file(run.workspace, path)
    except FilesystemToolError as exc:
        # Path rules are enforced by the Filesystem server (traversal, device names, ...).
        status_code = 404 if exc.code in ("FILE_NOT_FOUND", "WORKSPACE_NOT_FOUND") else 400
        raise ServiceError(status_code, exc.code, exc.message) from None
    return FileContent(path=path, content=content)


@router.get("/runs/{run_id}/reviews")
def run_reviews(run_id: str, session: SessionDep) -> list[ReviewOut]:
    return [ReviewOut.model_validate(r) for r in load_run(session, run_id).reviews]


@router.get("/runs/{run_id}/tests")
def run_tests(run_id: str, session: SessionDep) -> list[TestRunOut]:
    return [TestRunOut.model_validate(t) for t in load_run(session, run_id).test_runs]


@router.get("/runs/{run_id}/approvals")
def run_approvals(run_id: str, session: SessionDep) -> list[ApprovalOut]:
    return [ApprovalOut.model_validate(a) for a in load_run(session, run_id).approvals]


@router.get("/runs/{run_id}/report")
async def run_report(run_id: str, session: SessionDep, runtime: RuntimeDep) -> Report:
    run = load_run(session, run_id)
    usage: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for call in run.calls:
        totals = usage[call.agent]
        totals[0] += 1
        totals[1] += call.input_tokens
        totals[2] += call.output_tokens
    latest_files: dict[str, int] = {}
    for row in run.files:
        latest_files[row.path] = row.size_bytes
    return Report(
        run=run_out(session, run),
        steps=[StepOut.model_validate(s) for s in run.steps],
        final_review=ReviewOut.model_validate(run.reviews[-1]) if run.reviews else None,
        final_tests=TestRunOut.model_validate(run.test_runs[-1]) if run.test_runs else None,
        files=[FileEntry(path=p, size_bytes=s) for p, s in sorted(latest_files.items())],
        usage_by_agent=[
            AgentUsage(agent=a, calls=c, input_tokens=i, output_tokens=o)
            for a, (c, i, o) in sorted(usage.items())
        ],
    )


@router.post("/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(
    run_id: str, manager: Annotated[RunManager, Depends(get_manager)]
) -> CancelAccepted:
    return CancelAccepted(run_id=run_id, status=manager.cancel(run_id))


@router.post("/approvals/{approval_id}")
async def decide_approval(
    approval_id: str, body: Decision, manager: Annotated[RunManager, Depends(get_manager)]
) -> ApprovalOut:
    answers = list(body.answers) or ([body.answer] if body.answer else [])
    approval = manager.decide(approval_id, body.decision, answers, body.message)
    return ApprovalOut.model_validate(approval)
