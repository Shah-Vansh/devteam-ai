"""Runs workflows in the background for the API.

One asyncio task per active run drives the LangGraph graph until it finishes or pauses.
After every node the state is copied into the database and a `step` event is published.
A pause becomes a pending approval; answering it starts a new task that resumes the run
from its checkpoint, so approvals still work after the API restarts.
"""

import asyncio
import logging
from typing import Any

from langgraph.types import Command
from sqlalchemy import func, select

from app.db.models import AgentStep, Approval, Project, Run, utcnow
from app.db.session import Database
from app.services.errors import ServiceError, not_found
from app.services.events import EventBroker
from app.services.runtime import Runtime
from app.services.sync import ensure_approval, sync_files, sync_run
from app.workflow.graph import Step, advance, current
from app.workflow.state import TERMINAL
from app.workflow.workspace_io import new_run_id, read_all

logger = logging.getLogger("app.services.run_manager")

ACTIVE = ("RUNNING", "PAUSED")
DECISIONS = {"approve": "approved", "reject": "rejected", "cancel": "cancelled"}


def build_reply(kind: str, decision: str, answers: list[str], message: str | None) -> dict:
    """Turn an API decision into what the paused node expects."""
    if decision == "cancel":
        return {"action": "cancel"}
    if kind == "clarify":
        # Rejecting the questions means: keep the Planner's assumptions.
        return {"answers": answers if decision == "approve" else []}
    reply: dict[str, Any] = {"approved": decision == "approve"}
    if kind == "commit" and decision == "approve" and message:
        reply["message"] = message
    return reply


class RunManager:
    def __init__(self, db: Database, runtime: Runtime, events: EventBroker) -> None:
        self.db = db
        self.runtime = runtime
        self.events = events
        self._tasks: dict[str, asyncio.Task] = {}

    # ---------- lifecycle ----------

    def recover_after_restart(self) -> int:
        """Runs marked RUNNING lost their task when the API stopped. Paused runs are fine:
        their checkpoint and pending approval survive a restart."""
        with self.db.session() as session:
            stale = session.scalars(select(Run).where(Run.status == "RUNNING")).all()
            for run in stale:
                run.status = "ERROR"
                run.error = "the backend stopped while this run was active"
                run.finished_at = utcnow()
            return len(stale)

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def is_running(self, run_id: str) -> bool:
        return run_id in self._tasks

    # ---------- commands from the API ----------

    def start_run(self, project_id: str) -> Run:
        self._require_llm()
        with self.db.session() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise not_found("project", project_id)
            active = session.scalars(
                select(Run).where(Run.project_id == project_id, Run.status.in_(ACTIVE))
            ).first()
            if active is not None:
                raise ServiceError(
                    409,
                    "RUN_ALREADY_ACTIVE",
                    f"project {project_id} already has an active run",
                    {"run_id": active.id},
                )
            run = Run(id=new_run_id(), project_id=project_id, model=self.runtime.model)
            session.add(run)
            requirement = project.requirement
        initial = {"requirement": requirement, "model": self.runtime.model or ""}
        self._launch(run.id, initial)
        return run

    def decide(
        self, approval_id: str, decision: str, answers: list[str], message: str | None
    ) -> Approval:
        with self.db.session() as session:
            approval = session.get(Approval, approval_id)
            if approval is None:
                raise not_found("approval", approval_id)
            if approval.status != "pending":
                raise ServiceError(
                    400, "APPROVAL_ALREADY_DECIDED", f"approval {approval_id} is {approval.status}"
                )
            run = session.get(Run, approval.run_id)
            if run.status != "PAUSED" or self.is_running(run.id):
                raise ServiceError(400, "RUN_NOT_PAUSED", f"run {run.id} is {run.status}")
            if decision != "cancel":
                self._require_llm()
            reply = build_reply(approval.kind, decision, answers, message)
            approval.status = DECISIONS[decision]
            approval.answer = reply
            approval.decided_at = utcnow()
            run.status = "RUNNING"
            run_id = run.id
        self.events.publish(
            run_id, "approval_decided", {"approval_id": approval_id, "decision": decision}
        )
        self._launch(run_id, Command(resume=reply))
        return approval

    def cancel(self, run_id: str) -> str:
        with self.db.session() as session:
            run = session.get(Run, run_id)
            if run is None:
                raise not_found("run", run_id)
            if run.status in TERMINAL or run.status == "ERROR":
                raise ServiceError(
                    400, "RUN_FINISHED", f"run {run_id} already ended ({run.status})"
                )
            pending = session.scalars(
                select(Approval).where(Approval.run_id == run_id, Approval.status == "pending")
            ).first()
            pending_id = pending.id if pending is not None and run.status == "PAUSED" else None
        if pending_id is not None:
            # A paused run is cancelled through its pause, so the graph records it.
            self.decide(pending_id, "cancel", [], None)
            return "CANCELLING"
        task = self._tasks.get(run_id)
        if task is not None:
            task.cancel()  # _drive records CANCELLED when the task stops
            return "CANCELLING"
        self._finish(run_id, "CANCELLED", "cancelled")
        return "CANCELLED"

    # ---------- driving a run ----------

    def _require_llm(self) -> None:
        if self.runtime.make_deps is None:
            raise ServiceError(
                503, "LLM_NOT_CONFIGURED", self.runtime.llm_error or "LLM not configured"
            )

    def _launch(self, run_id: str, value: dict | Command) -> None:
        task = asyncio.create_task(self._drive(run_id, value), name=f"run-{run_id}")
        self._tasks[run_id] = task

        def forget(done: asyncio.Task) -> None:
            if self._tasks.get(run_id) is done:
                del self._tasks[run_id]

        task.add_done_callback(forget)

    async def _drive(self, run_id: str, value: dict | Command) -> None:
        last_message = {"text": ""}

        def progress(message: str) -> None:
            last_message["text"] = message
            self.events.publish(run_id, "log", {"message": message})

        deps = self.runtime.make_deps(progress)
        graph = self.runtime.graph
        if isinstance(value, Command):
            saved = await current(graph, run_id)
            state: dict[str, Any] = dict(saved.state) if saved else {}
        else:
            state = dict(value)

        async def on_node(node: str, update: dict[str, Any]) -> None:
            state.update(update)
            with self.db.session() as session:
                run = session.get(Run, run_id)
                run.current_step = node
                sync_run(session, run, state, None)
                done_before = session.scalar(
                    select(func.count()).where(AgentStep.run_id == run_id, AgentStep.agent == node)
                )
                session.add(
                    AgentStep(
                        run_id=run_id,
                        agent=node,
                        round=(done_before or 0) + 1,
                        status=state.get("status", "RUNNING"),
                        summary=last_message["text"][:1000],
                        finished_at=utcnow(),
                    )
                )
            # A step that logs nothing (a pause, prepare_commit) must not repeat the
            # previous step's line as its own summary.
            last_message["text"] = ""
            self.events.publish(
                run_id, "step", {"node": node, "status": state.get("status", "RUNNING")}
            )

        try:
            step = await advance(graph, run_id, deps, value, on_node=on_node)
        except asyncio.CancelledError:
            self._finish(run_id, "CANCELLED", "cancelled while running")
            raise
        except Exception as exc:  # nodes already turn expected failures into statuses
            logger.exception("run_failed", extra={"fields": {"run_id": run_id}})
            self._finish(run_id, "ERROR", f"unexpected error: {type(exc).__name__}")
            return
        await self._settle(run_id, step)

    async def _settle(self, run_id: str, step: Step) -> None:
        """Record where the run stopped: a pause (approval) or the end."""
        files: dict[str, str] = {}
        if step.state.get("workspace"):
            try:
                files = await read_all(self.runtime.fs, step.state["workspace"])
            except Exception:  # noqa: BLE001 - metadata only; the run result matters more
                logger.warning("file_listing_failed", extra={"fields": {"run_id": run_id}})
        with self.db.session() as session:
            run = session.get(Run, run_id)
            sync_run(session, run, step.state, step.pause)
            sync_files(session, run, files)
            approval_id = ensure_approval(session, run, step.pause).id if step.pause else None
        if step.pause is not None:
            self.events.publish(
                run_id,
                "approval_required",
                {"approval_id": approval_id, "kind": step.pause["kind"], "payload": step.pause},
            )
        else:
            self.events.publish(
                run_id,
                "finished",
                {"status": step.state.get("status"), "stop_reason": step.state.get("stop_reason")},
            )

    def _finish(self, run_id: str, status: str, reason: str) -> None:
        with self.db.session() as session:
            run = session.get(Run, run_id)
            if run is not None:
                run.status = status
                run.error = reason
                run.finished_at = utcnow()
                for approval in session.scalars(
                    select(Approval).where(Approval.run_id == run_id, Approval.status == "pending")
                ):
                    approval.status = "cancelled"
                    approval.decided_at = utcnow()
        self.events.publish(run_id, "finished", {"status": status, "stop_reason": reason})
