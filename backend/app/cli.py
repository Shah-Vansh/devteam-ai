"""Command-line entry point.

python -m app.cli plan "Build a todo API with create, list and delete"
python -m app.cli plan --model openai/gpt-oss-20b "..."
python -m app.cli fs-demo
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from app.agents.planner import Planner, PlannerInputError
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.llm.base import LLMError
from app.llm.factory import build_llm_client
from app.mcp_clients.filesystem import FilesystemClient, FilesystemToolError

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="devteam")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Turn a requirement into a project plan")
    plan.add_argument("requirement")
    plan.add_argument("--model", default=None, help="Override LLM_MODEL for this call")
    plan.set_defaults(handler=cmd_plan)

    demo = sub.add_parser("fs-demo", help="Start the Filesystem MCP server and exercise it")
    demo.set_defaults(handler=cmd_fs_demo)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
