"""Run the end-to-end benchmark (docs/EVALUATION.md).

    python eval/run_benchmark.py                      # all 10 cases
    python eval/run_benchmark.py --only b01,b02       # some cases
    python eval/run_benchmark.py --resume FILE        # continue a results file

Every case runs the real workflow: Groq for the agents, E2B for the tests, a real local
commit. Pauses are approved automatically. Results go to eval/results/ after every case,
so a run stopped by a provider quota can be resumed later with --resume.
"""

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.developer import Developer
from app.agents.planner import Planner
from app.agents.reviewer import Reviewer
from app.agents.tester import Tester
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.evaluation.benchmark import (
    CaseResult,
    aggregate,
    is_rate_limited,
    markdown_table,
    run_case,
)
from app.execution.factory import build_executor
from app.gitops.repo import CommitAuthor
from app.llm.factory import build_llm_client
from app.mcp_clients.filesystem import FilesystemClient
from app.mcp_clients.git import GitClient
from app.workflow.graph import build_graph
from app.workflow.state import WorkflowDeps
from app.workflow.workspace_io import new_run_id

EVAL_DIR = Path(__file__).resolve().parent


def save(path: Path, meta: dict, results: list[CaseResult]) -> None:
    data = {**meta, "summary": aggregate(results), "cases": [r.as_dict() for r in results]}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


async def main(args: argparse.Namespace) -> int:
    settings = get_settings()
    if args.reasoning_effort:
        settings = settings.model_copy(update={"llm_reasoning_effort": args.reasoning_effort})
    configure_logging("WARNING", settings.secret_values())
    model = args.model or settings.llm_model
    cases = json.loads((EVAL_DIR / "benchmark.json").read_text(encoding="utf-8"))
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]

    out = (
        Path(args.resume)
        if args.resume
        else (
            EVAL_DIR / "results" / f"{date.today().isoformat()}-e2e-{model.replace('/', '_')}.json"
        )
    )
    results: list[CaseResult] = []
    if args.resume and out.exists():
        saved = json.loads(out.read_text(encoding="utf-8"))
        # Keep finished cases; redo those stopped by rate limits (they clear with time).
        results = [CaseResult(**c) for c in saved["cases"] if not is_rate_limited(c["stop_reason"])]
    done = {r.id for r in results}
    meta = {
        "model": model,
        "reasoning_effort": settings.llm_reasoning_effort,
        "executor": settings.executor,
        "date": date.today().isoformat(),
    }

    llm = build_llm_client(settings, model=model)
    executor = build_executor(settings)
    author = CommitAuthor(settings.commit_author_name, settings.commit_author_email)
    settings.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
    async with (
        AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db_path)) as saver,
        FilesystemClient.over_stdio(settings.workspaces_dir) as fs,
        GitClient.over_stdio(settings.workspaces_dir, author) as git,
    ):
        app = build_graph().compile(checkpointer=saver)
        for case in cases:
            if case["id"] in done:
                continue
            run_id = new_run_id()
            print(f"{case['id']} ({case['difficulty']}) run {run_id} ...", flush=True)
            deps = WorkflowDeps(
                planner=Planner(llm),
                developer=Developer(llm),
                reviewer=Reviewer(llm),
                tester=Tester(llm),
                executor=executor,
                fs=fs,
                git=git,
                max_review_rounds=settings.max_review_rounds,
                max_fix_rounds=settings.max_fix_rounds,
                max_llm_calls=settings.max_llm_calls_per_run,
                test_timeout_seconds=settings.sandbox_timeout_seconds,
                progress=lambda msg: print(f"    {msg}", flush=True) if args.verbose else None,
            )
            result = await run_case(app, deps, run_id, case, model)
            results.append(result)
            save(out, meta, results)
            print(
                f"  -> {result.status} tests {result.tests_passed}/{result.tests_total} "
                f"llm {result.llm_calls} in {result.seconds:.0f}s"
                + (f" ({result.stop_reason[:120]})" if result.stop_reason else ""),
                flush=True,
            )
            if not args.keep_going and is_rate_limited(result.stop_reason):
                print("provider quota reached; resume later with --resume", flush=True)
                break
            await asyncio.sleep(args.pause)  # never block the event loop (MCP runs on it)

    results.sort(key=lambda r: r.id)
    save(out, meta, results)
    print("\n" + markdown_table(results))
    print("\n" + json.dumps(aggregate(results), indent=2))
    print(f"\nresults: {out}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=None)
    parser.add_argument("--only", default=None, help="comma-separated case ids")
    parser.add_argument("--resume", default=None, help="results file to continue")
    parser.add_argument("--reasoning-effort", default=None, choices=["low", "medium", "high"])
    parser.add_argument("--pause", type=float, default=20.0, help="seconds between cases")
    parser.add_argument(
        "--keep-going", action="store_true", help="continue after a provider quota error"
    )
    parser.add_argument("--verbose", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args())))
