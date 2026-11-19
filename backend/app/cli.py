"""Command-line entry point.

python -m app.cli plan "Build a todo API with create, list and delete"
python -m app.cli plan --model openai/gpt-oss-20b "..."
"""

import argparse
import json
import logging
import sys

from app.agents.planner import Planner, PlannerInputError
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.llm.base import LLMError
from app.llm.factory import build_llm_client

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="devteam")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="Turn a requirement into a project plan")
    plan.add_argument("requirement")
    plan.add_argument("--model", default=None, help="Override LLM_MODEL for this call")
    plan.set_defaults(handler=cmd_plan)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
