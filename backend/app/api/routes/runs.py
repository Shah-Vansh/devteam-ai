import io
import json
import zipfile
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy import func, select
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
    GitCommit,
    GitFile,
    GitInfo,
    PreviewOut,
    Report,
    ReviewOut,
    RunOut,
    StepOut,
    TestRunOut,
    Usage,
)
from app.db.models import Approval, LLMCall, Run
from app.mcp_clients.filesystem import FilesystemToolError
from app.mcp_clients.git import GitToolError
from app.services.errors import ServiceError, not_found
from app.services.events import EventBroker
from app.services.previews import PreviewInfo
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


# Files the Filesystem server lists but will not read (binary or too large).
UNREADABLE = {"EXTENSION_NOT_ALLOWED", "FILE_TOO_LARGE"}


async def read_all_files(runtime: Runtime, run: Run) -> dict[str, str]:
    """Every file of the run's workspace, read through the read-only Filesystem view."""
    if not run.workspace:
        raise ServiceError(404, "FILE_NOT_FOUND", f"run {run.id} has no files yet")
    view = runtime.fs.read_only()
    files: dict[str, str] = {}
    try:
        listing = await view.call("list_files", {"workspace": run.workspace})
        for entry in listing["files"]:
            try:
                files[entry["path"]] = await view.read_file(run.workspace, entry["path"])
            except FilesystemToolError as exc:
                # Found live: running the app locally left __pycache__/*.pyc files, which
                # the server does not read. They are not part of the project; skip them.
                if exc.code not in UNREADABLE:
                    raise
    except FilesystemToolError as exc:
        status_code = 404 if exc.code in ("FILE_NOT_FOUND", "WORKSPACE_NOT_FOUND") else 400
        raise ServiceError(status_code, exc.code, exc.message) from None
    return files


@router.get("/runs/{run_id}/archive", response_class=Response)
async def download_run(run_id: str, session: SessionDep, runtime: RuntimeDep) -> Response:
    """The generated project as a ZIP file, in a folder named after the workspace."""
    run = load_run(session, run_id)
    files = await read_all_files(runtime, run)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in sorted(files.items()):
            archive.writestr(f"{run.workspace}/{path}", content)
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{run.workspace}.zip"'},
    )


def preview_out(info: PreviewInfo) -> PreviewOut:
    expires = datetime.fromtimestamp(info.expires_at, UTC) if info.expires_at else None
    return PreviewOut(status=info.status, url=info.url, expires_at=expires)


@router.get("/runs/{run_id}/preview")
def preview_status(run_id: str, runtime: RuntimeDep) -> PreviewOut:
    return preview_out(runtime.previews.info(run_id))


@router.post("/runs/{run_id}/preview")
async def start_preview(run_id: str, session: SessionDep, runtime: RuntimeDep) -> PreviewOut:
    """Start the generated API in an E2B sandbox for a few minutes ("Try the API"). Only
    for a run whose tests passed: code that failed its tests is not worth a sandbox."""
    run = load_run(session, run_id)
    if run.test_status != "PASSED":
        raise ServiceError(
            409, "PREVIEW_NOT_ALLOWED", "Only a run whose tests passed can be started."
        )
    files = await read_all_files(runtime, run)
    return preview_out(await runtime.previews.start(run_id, files))


@router.post("/runs/{run_id}/preview/stop")
async def stop_preview(run_id: str, runtime: RuntimeDep) -> PreviewOut:
    return preview_out(await runtime.previews.stop(run_id))


@router.get("/usage")
def usage(session: SessionDep, runtime: RuntimeDep) -> Usage:
    window = 24
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=window)
    used = session.scalar(
        select(func.coalesce(func.sum(LLMCall.input_tokens + LLMCall.output_tokens), 0)).where(
            LLMCall.created_at >= since
        )
    )
    recent = session.scalars(
        select(Run)
        .where(Run.finished_at.is_not(None), Run.input_tokens > 0)
        .order_by(Run.started_at.desc())
        .limit(10)
    ).all()
    typical = (
        round(sum(r.input_tokens + r.output_tokens for r in recent) / len(recent))
        if recent
        else None
    )
    limit = runtime.daily_token_limit
    return Usage(
        window_hours=window,
        tokens_used=int(used or 0),
        daily_limit=limit,
        tokens_left=max(0, limit - int(used or 0)) if limit else None,
        typical_run_tokens=typical,
    )


@router.get("/runs/{run_id}/git")
async def run_git(run_id: str, session: SessionDep, runtime: RuntimeDep) -> GitInfo:
    """Repository status and history of the run's workspace (read-only Git tools)."""
    run = load_run(session, run_id)
    empty = GitInfo(initialized=False, branch=None, clean=None, files=[], commits=[])
    if not run.workspace:
        return empty
    try:
        status_data = await runtime.git.get_git_status(run.workspace)
        commits = await runtime.git.get_commit_history(run.workspace, limit=20)
    except GitToolError as exc:
        if exc.code in ("NOT_A_REPOSITORY", "WORKSPACE_NOT_FOUND"):
            return empty
        raise ServiceError(400, exc.code, exc.message) from None
    return GitInfo(
        initialized=True,
        branch=status_data["branch"],
        clean=status_data["clean"],
        files=[GitFile(**f) for f in status_data["files"]],
        commits=[GitCommit(**c) for c in commits],
    )


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
