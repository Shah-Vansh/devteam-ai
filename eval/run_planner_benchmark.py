"""Run the Planner on every benchmark requirement and record the results.

    python eval/run_planner_benchmark.py                       # model from .env
    python eval/run_planner_benchmark.py --model openai/gpt-oss-20b

Writes eval/results/<date>-planner-<model>.json and prints a summary table.
Measures whether a valid plan is produced, not whether the plan is good;
plan quality is judged later by whether generated code passes its tests.
"""

import argparse
import json
import time
from datetime import date
from pathlib import Path

from app.agents.planner import Planner
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.llm.base import LLMError
from app.llm.factory import build_llm_client

EVAL_DIR = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None)
    parser.add_argument("--pause", type=float, default=2.0, help="Seconds between calls")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging("WARNING", settings.secret_values())
    llm = build_llm_client(settings, model=args.model)
    planner = Planner(llm)
    cases = json.loads((EVAL_DIR / "benchmark.json").read_text(encoding="utf-8"))

    rows = []
    for case in cases:
        start = time.perf_counter()
        row = {"id": case["id"], "difficulty": case["difficulty"]}
        try:
            result = planner.plan(case["requirement"])
            plan = result.plan
            row |= {
                "valid": True,
                "attempts": result.attempts,
                "files": len(plan.files),
                "tasks": len(plan.tasks),
                "open_questions": len(plan.open_questions),
                "complexity": plan.complexity,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
            }
        except LLMError as exc:
            row |= {"valid": False, "error": str(exc)[:200]}
        row["seconds"] = round(time.perf_counter() - start, 1)
        rows.append(row)
        print(json.dumps(row))
        time.sleep(args.pause)

    valid = [r for r in rows if r["valid"]]
    summary = {
        "model": llm.model,
        "date": date.today().isoformat(),
        "valid": f"{len(valid)}/{len(rows)}",
        "retries_needed": sum(1 for r in valid if r["attempts"] > 1),
        "avg_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 1),
        "avg_output_tokens": round(sum(r["output_tokens"] for r in valid) / max(len(valid), 1)),
        "cases_with_questions": sum(1 for r in valid if r["open_questions"] > 0),
    }
    out_dir = EVAL_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"{summary['date']}-planner-{llm.model.replace('/', '_')}.json"
    out_file.write_text(json.dumps({"summary": summary, "cases": rows}, indent=2), encoding="utf-8")
    print("\nSUMMARY", json.dumps(summary, indent=2))
    print(f"saved {out_file.relative_to(EVAL_DIR.parent)}")


if __name__ == "__main__":
    main()
