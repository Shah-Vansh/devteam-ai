"""Command-line entry point.

python -m app.cli plan "Build a todo API with create, list and delete"
python -m app.cli plan --model openai/gpt-oss-20b "..."
python -m app.cli plan "..." > plan.json
python -m app.cli build "Build a todo API with create, list and delete"
python -m app.cli build --plan plan.json --yes
python -m app.cli fs-demo
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from app.agents.common import AgentOutputError
from app.agents.developer import Developer
from app.agents.planner import Planner, PlannerInputError
from app.agents.reviewer import Reviewer, sort_findings
from app.agents.tester import Tester
from app.core.config import REPO_ROOT, Settings, get_settings
from app.core.logging import configure_logging
from app.execution.factory import build_executor
from app.llm.base import LLMError
from app.llm.factory import build_llm_client
from app.mcp_clients.filesystem import FilesystemClient, FilesystemToolError
from app.pipeline.budget import LLMBudget, LLMBudgetExceeded
from app.pipeline.develop import new_workspace_name
from app.pipeline.run import TestRound, build_and_test
from app.schemas.plan import ProjectPlan
from app.schemas.review import ReviewReport

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


async def _build(args: argparse.Namespace, settings: Settings) -> int:
    llm = build_llm_client(settings, model=args.model)
    if args.plan:
        plan = ProjectPlan.model_validate_json(_read_text_any(Path(args.plan)))
        print(f"Using saved plan {args.plan!r}")
    else:
        print("planner: planning")
        plan = (await asyncio.to_thread(Planner(llm).plan, args.requirement)).plan
    print(f"plan: {plan.project_name}, {len(plan.files)} files, {len(plan.tasks)} tasks")
    for question in plan.open_questions:
        print(f"  open question (continuing with assumptions): {question}")

    workspace = new_workspace_name(plan.project_name)
    # Run records (plan and every review) go to data/runs/, which git ignores. They are
    # kept outside the workspace so they never become part of the generated project.
    run_dir = REPO_ROOT / "data" / "runs" / workspace
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    def save_report(report: ReviewReport) -> None:
        data = report.model_dump() | {"verdict": report.verdict}
        path = run_dir / f"review-{report.round}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def save_test_round(test_round: TestRound) -> None:
        data = {
            "round": test_round.round,
            "result": test_round.result.model_dump(),
            "triage": test_round.triage.model_dump() if test_round.triage else None,
        }
        path = run_dir / f"tests-{test_round.round}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    executor = build_executor(settings)

    async def approve_execution() -> bool:
        # Human approval before code leaves this machine and runs (Phase 5 turns this
        # into a LangGraph interrupt).
        if executor.name == "static_only" or args.yes:
            return True
        answer = await asyncio.to_thread(
            input, f"\nRun the generated tests in the {executor.name} sandbox? [y/N] "
        )
        return answer.strip().lower() in ("y", "yes")

    print(f"Run record: {run_dir}")
    budget = LLMBudget(settings.max_llm_calls_per_run)
    async with FilesystemClient.over_stdio(settings.workspaces_dir) as fs:
        result = await build_and_test(
            plan,
            workspace=workspace,
            developer=Developer(llm),
            reviewer=Reviewer(llm),
            tester=Tester(llm),
            executor=executor,
            fs=fs,
            budget=budget,
            approve_execution=approve_execution,
            max_review_rounds=settings.max_review_rounds,
            max_fix_rounds=settings.max_fix_rounds,
            test_timeout_seconds=settings.sandbox_timeout_seconds,
            progress=lambda msg: print(f"  {msg}"),
            on_report=save_report,
            on_test_round=save_test_round,
        )
        files = await fs.list_files(workspace)

    summary = {
        "workspace": workspace,
        "status": result.status,
        "stop_reason": result.stop_reason,
        "review_status": result.develop.status,
        "review_rounds": result.develop.review_rounds,
        "fix_rounds": result.fix_rounds,
        "test_runs": len(result.test_rounds),
        "llm_calls": budget.calls,
        "input_tokens": budget.input_tokens,
        "output_tokens": budget.output_tokens,
    }
    (run_dir / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    report = result.develop.final_report
    print(f"\nResult: {result.status}")
    if result.stop_reason:
        print(f"Reason: {result.stop_reason}")
    print(f"Review: {result.develop.status} after {len(result.develop.reports)} review(s)")
    print(f"  {report.summary}")
    for f in sort_findings(report.findings):
        where = f"{f.file}:{f.line}" if f.line else f.file
        print(f"  [{f.severity:<6}] {f.source:<8} {where}  {f.message}")
    tests = result.last_test_result
    if tests is None:
        print("Tests: not run")
    else:
        print(
            f"Tests ({tests.executor}): {tests.status}, passed {tests.passed}, failed "
            f"{tests.failed}, errors {tests.errors}, fix rounds {result.fix_rounds}"
        )
        if tests.detail:
            print(f"  {tests.detail}")
        for case in tests.failures:
            first_line = case.message.splitlines()[0] if case.message else ""
            print(f"  FAILED {case.name}  {first_line[:120]}")
    print(f"\nFiles: {', '.join(files)}")
    print(f"Workspace: {settings.workspaces_dir / workspace}")
    print(f"LLM calls: {budget.calls}, tokens in {budget.input_tokens}, out {budget.output_tokens}")
    return {"TESTS_PASSED": 0, "NOT_EXECUTED": 4}.get(result.status, 3)


def cmd_build(args: argparse.Namespace) -> int:
    if not args.requirement and not args.plan:
        print("give a requirement or --plan <file>", file=sys.stderr)
        return 2
    settings = get_settings()
    configure_logging(settings.log_level, settings.secret_values())
    try:
        return asyncio.run(_build(args, settings))
    except (PlannerInputError, LLMError, AgentOutputError, LLMBudgetExceeded) as exc:
        logger.error("build_failed", extra={"fields": {"error": str(exc)}})
        return 1


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
        "--yes", action="store_true", help="Run tests in the sandbox without asking first"
    )
    build.set_defaults(handler=cmd_build)

    demo = sub.add_parser("fs-demo", help="Start the Filesystem MCP server and exercise it")
    demo.set_defaults(handler=cmd_fs_demo)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
