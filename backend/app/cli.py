"""Command-line entry point.

python -m app.cli plan "Build a todo API with create, list and delete"
python -m app.cli plan --model openai/gpt-oss-20b "..."
python -m app.cli plan "..." > plan.json
python -m app.cli build "Build a todo API with create, list and delete"
python -m app.cli build --plan plan.json --yes
python -m app.cli resume <run-id>
python -m app.cli status <run-id>
python -m app.cli fs-demo
"""

import argparse
import asyncio
import json
import logging
import secrets
import sys
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from app.agents.developer import Developer
from app.agents.planner import Planner, PlannerInputError
from app.agents.reviewer import Reviewer, sort_findings
from app.agents.tester import Tester
from app.core.config import REPO_ROOT, Settings, get_settings
from app.core.logging import configure_logging
from app.execution.base import ExecutionResult
from app.execution.factory import build_executor
from app.llm.base import LLMError
from app.llm.factory import build_llm_client
from app.mcp_clients.filesystem import FilesystemClient, FilesystemToolError
from app.schemas.plan import ProjectPlan
from app.schemas.review import ReviewReport
from app.workflow.graph import Step, advance, build_graph, current
from app.workflow.state import WorkflowDeps

logger = logging.getLogger("app.cli")


def cmd_plan(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())
    try:
        planner = Planner(build_llm_client(settings, model=args.model))
        result = planner.plan(args.requirement)
    except (PlannerInputError, LLMError) as exc:
        logger.error("plan_failed", extra={"fields": {"error": str(exc)}})
        return 1

    print(json.dumps(result.plan.model_dump(), indent=2))
    usage = result.usage
    print(
        f"\nmodel={usage.model} input_tokens={usage.input_tokens} "
        f"output_tokens={usage.output_tokens} latency_ms={usage.latency_ms} "
        f"attempts={result.attempts}",
        file=sys.stderr,
    )
    return 0


async def _fs_demo(workspaces_dir: Path) -> None:
    async with FilesystemClient.over_stdio(workspaces_dir) as fs:
        print("Tools offered by the Filesystem MCP server:")
        for tool in await fs.list_tools():
            mode = "read-only" if tool.annotations.read_only_hint else "writes"
            print(f"  {tool.name:<12} ({mode}) {tool.description}")

        workspace = "fs-demo"
        try:
            await fs.create_file(workspace, "app/main.py", "print('hello')\n")
        except FilesystemToolError as exc:
            if exc.code != "FILE_EXISTS":  # second run: file is already there
                raise
        print(f"\nFiles in {workspace!r}: {await fs.list_files(workspace)}")

        print("\nAttack attempts (all should be refused):")
        for path in ("../../.env.txt", "C:/Windows/win.ini", "con.py", "payload.exe"):
            try:
                await fs.read_file(workspace, path)
                print(f"  {path:<22} READ - this is a bug")
            except FilesystemToolError as exc:
                print(f"  {path:<22} refused: {exc.code}")

        agent_view = fs.read_only()
        names = [t.name for t in await agent_view.list_tools()]
        print(f"\nAn agent's read-only view sees only: {names}")


def cmd_fs_demo(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())
    asyncio.run(_fs_demo(settings.workspaces_dir))
    return 0


def _read_text_any(path: Path) -> str:
    """PowerShell's `>` writes UTF-16; accept that as well as UTF-8."""
    raw = path.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


# ---------- runs (LangGraph workflow) ----------


def new_run_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


def run_dir(run_id: str) -> Path:
    # Run records live in data/runs/ (git-ignored), never inside the generated project.
    return REPO_ROOT / "data" / "runs" / run_id


@asynccontextmanager
async def open_workflow(settings: Settings, model: str | None, args: argparse.Namespace):
    """Everything a start or resume needs: the compiled graph with its SQLite checkpointer,
    and fresh live dependencies (LLM client, MCP connection, executor)."""
    llm = build_llm_client(settings, model=model)
    settings.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
    async with (
        AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db_path)) as saver,
        FilesystemClient.over_stdio(settings.workspaces_dir) as fs,
    ):
        deps = WorkflowDeps(
            planner=Planner(llm),
            developer=Developer(llm),
            reviewer=Reviewer(llm),
            tester=Tester(llm),
            executor=build_executor(settings),
            fs=fs,
            max_review_rounds=settings.max_review_rounds,
            max_fix_rounds=settings.max_fix_rounds,
            max_llm_calls=settings.max_llm_calls_per_run,
            test_timeout_seconds=settings.sandbox_timeout_seconds,
            ask_clarifications=not args.yes,
            auto_approve_execution=args.yes,
            progress=lambda msg: print(f"  {msg}"),
        )
        yield build_graph().compile(checkpointer=saver), deps


async def prompt(text: str) -> str | None:
    """One line from the user, or None when there is nobody to ask. `isatty()` is not
    enough: on Windows the NUL device counts as a terminal, and reading it gives EOF."""
    if not sys.stdin.isatty():
        return None
    try:
        return (await asyncio.to_thread(input, text)).strip()
    except EOFError:
        return None


async def ask_human(pause: dict[str, Any]) -> dict[str, Any] | None:
    """Answer a pause at the terminal. None leaves the run paused for `resume` later."""
    if pause["kind"] == "clarify":
        print("\nThe Planner has questions. Answer each, press Enter to keep its assumption,")
        print("or type 'cancel' or 'later'.")
        answers = []
        for question in pause["questions"]:
            reply = await prompt(f"  {question}\n  > ")
            if reply is None or reply.lower() == "later":
                return None
            if reply.lower() == "cancel":
                return {"action": "cancel"}
            answers.append(reply)
        return {"answers": answers}
    reply = await prompt(
        f"\nRun the generated tests in the {pause['executor']} sandbox? [y/N/cancel/later] "
    )
    if reply is None:
        return None
    reply = reply.lower()
    if reply == "later":
        return None
    if reply == "cancel":
        return {"action": "cancel"}
    return {"approved": reply in ("y", "yes")}


AUTO_REPLIES = {"clarify": {"answers": []}, "execute": {"approved": True}}


async def drive(app, run_id: str, deps: WorkflowDeps, step: Step, auto: bool) -> Step:
    """Answer pauses until the run finishes. With `auto` (--yes), keep the Planner's
    assumptions and approve execution; otherwise ask at the terminal."""
    while step.pause is not None:
        reply = AUTO_REPLIES[step.pause["kind"]] if auto else await ask_human(step.pause)
        if reply is None:
            break
        step = await advance(app, run_id, deps, Command(resume=reply))
    return step


def save_records(run_id: str, step: Step) -> None:
    state, folder = step.state, run_dir(run_id)
    folder.mkdir(parents=True, exist_ok=True)
    if state.get("plan"):
        (folder / "plan.json").write_text(json.dumps(state["plan"], indent=2), encoding="utf-8")
    for report in state.get("reports", []):
        path = folder / f"review-{report['round']}.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for test_round in state.get("test_rounds", []):
        path = folder / f"tests-{test_round['round']}.json"
        path.write_text(json.dumps(test_round, indent=2), encoding="utf-8")
    summary = {
        "run_id": run_id,
        "status": "PAUSED" if step.pause else state.get("status"),
        "paused_for": step.pause["kind"] if step.pause else None,
        "stop_reason": state.get("stop_reason", ""),
        "workspace": state.get("workspace"),
        "model": state.get("model"),
        "review_rounds": state.get("review_rounds", 0),
        "fix_rounds": state.get("fix_rounds", 0),
        "reviews": len(state.get("reports", [])),
        "test_runs": len(state.get("test_rounds", [])),
        "llm_calls": state.get("llm_calls", 0),
        "input_tokens": state.get("input_tokens", 0),
        "output_tokens": state.get("output_tokens", 0),
    }
    (folder / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def print_summary(run_id: str, step: Step, settings: Settings) -> int:
    state = step.state
    if step.pause:
        print(f"\nRun {run_id} is PAUSED, waiting for: {step.pause['kind']}")
        print(f"Continue later with:  python -m app.cli resume {run_id}")
        return 5
    print(f"\nResult: {state.get('status')}")
    if state.get("stop_reason"):
        print(f"Reason: {state['stop_reason']}")
    if state.get("reports"):
        report = ReviewReport.model_validate(state["reports"][-1])
        print(f"Review: {report.verdict} after {len(state['reports'])} review(s)")
        print(f"  {report.summary}")
        for f in sort_findings(report.findings):
            where = f"{f.file}:{f.line}" if f.line else f.file
            print(f"  [{f.severity:<6}] {f.source:<8} {where}  {f.message}")
    if state.get("test_rounds"):
        tests = ExecutionResult.model_validate(state["test_rounds"][-1]["result"])
        print(
            f"Tests ({tests.executor}): {tests.status}, passed {tests.passed}, failed "
            f"{tests.failed}, errors {tests.errors}, fix rounds {state.get('fix_rounds', 0)}"
        )
        if tests.detail:
            print(f"  {tests.detail}")
        for case in tests.failures:
            first_line = case.message.splitlines()[0] if case.message else ""
            print(f"  FAILED {case.name}  {first_line[:120]}")
    else:
        print("Tests: not run")
    if state.get("workspace"):
        print(f"\nWorkspace: {settings.workspaces_dir / state['workspace']}")
    print(f"Run record: {run_dir(run_id)}")
    print(
        f"LLM calls: {state.get('llm_calls', 0)}, tokens in {state.get('input_tokens', 0)}, "
        f"out {state.get('output_tokens', 0)}"
    )
    return {"TESTS_PASSED": 0, "NOT_EXECUTED": 4}.get(state.get("status"), 3)


async def _build(args: argparse.Namespace, settings: Settings) -> int:
    run_id = new_run_id()
    initial: dict[str, Any] = {"model": args.model or settings.llm_model}
    if args.plan:
        initial["plan"] = ProjectPlan.model_validate_json(
            _read_text_any(Path(args.plan))
        ).model_dump()
        print(f"Using saved plan {args.plan!r}")
    else:
        initial["requirement"] = args.requirement
    print(f"Run {run_id}")
    async with open_workflow(settings, args.model, args) as (app, deps):
        first = await advance(app, run_id, deps, initial)
        step = await drive(app, run_id, deps, first, args.yes)
    save_records(run_id, step)
    return print_summary(run_id, step, settings)


async def _resume(args: argparse.Namespace, settings: Settings) -> int:
    async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db_path)) as saver:
        saved = await current(build_graph().compile(checkpointer=saver), args.run_id)
    if saved is None:
        print(f"no run named {args.run_id!r}", file=sys.stderr)
        return 2
    if saved.pause is None:
        print(f"run {args.run_id} is not paused (status {saved.state.get('status')})")
        return print_summary(args.run_id, saved, settings)
    model = args.model or saved.state.get("model")
    async with open_workflow(settings, model, args) as (app, deps):
        step = await drive(app, args.run_id, deps, saved, args.yes)
    save_records(args.run_id, step)
    return print_summary(args.run_id, step, settings)


async def _status(args: argparse.Namespace, settings: Settings) -> int:
    async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db_path)) as saver:
        saved = await current(build_graph().compile(checkpointer=saver), args.run_id)
    if saved is None:
        print(f"no run named {args.run_id!r}", file=sys.stderr)
        return 2
    return print_summary(args.run_id, saved, settings)


def run_command(coro_factory) -> Callable[[argparse.Namespace], int]:
    def handler(args: argparse.Namespace) -> int:
        settings = get_settings()
        configure_logging(settings.log_level, settings.secret_values())
        try:
            return asyncio.run(coro_factory(args, settings))
        except (PlannerInputError, LLMError) as exc:
            # Only setup problems reach here (for example a missing API key); failures
            # inside a run end the run in a terminal state instead.
            logger.error("run_failed", extra={"fields": {"error": str(exc)}})
            return 1

    return handler


def main(argv: list[str] | None = None) -> int:
    # Model output often contains characters such as U+2011 (non-breaking hyphen) that a
    # Windows console code page cannot show. Replace them instead of crashing.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(prog="devteam")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Turn a requirement into a project plan")
    plan.add_argument("requirement")
    plan.add_argument("--model", default=None, help="Override LLM_MODEL for this call")
    plan.set_defaults(handler=cmd_plan)

    build = sub.add_parser("build", help="Plan, write, review and test a project")
    build.add_argument("requirement", nargs="?", default="")
    build.add_argument("--plan", default=None, help="Use a saved plan JSON instead of planning")
    build.add_argument("--model", default=None, help="Override LLM_MODEL for this run")
    build.add_argument(
        "--yes",
        action="store_true",
        help="Do not pause: keep the Planner's assumptions and run tests without asking",
    )
    build.set_defaults(handler=run_command(_build))

    resume = sub.add_parser("resume", help="Continue a paused run")
    resume.add_argument("run_id")
    resume.add_argument("--model", default=None, help="Override the model saved with the run")
    resume.add_argument("--yes", action="store_true", help="Approve remaining pauses")
    resume.set_defaults(handler=run_command(_resume))

    status = sub.add_parser("status", help="Show a run's saved state")
    status.add_argument("run_id")
    status.set_defaults(handler=run_command(_status))

    demo = sub.add_parser("fs-demo", help="Start the Filesystem MCP server and exercise it")
    demo.set_defaults(handler=cmd_fs_demo)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
