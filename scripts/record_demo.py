"""Record a finished run for the dashboard's demo mode.

    .venv\\Scripts\\python.exe scripts\\record_demo.py RUN_ID [--api http://127.0.0.1:8000]

Reads everything the dashboard shows for one run from a running API (run, project,
report, files, reviews, tests, git history, approvals) plus its event stream, and writes
frontend/src/demo/recording.json. The dashboard replays it at /runs/demo without a
backend, API keys or tokens.

The event stream must still be in the API's memory (record before restarting the API);
otherwise only a database snapshot is available and the replay would have no live log.
API responses never contain secrets; the recording is still checked for key-like
strings before it is written.
"""

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parents[1] / "frontend" / "src" / "demo" / "recording.json"
SECRET_LIKE = re.compile(r"(gsk_|e2b_|sk-)[A-Za-z0-9]{16,}|org_[a-z0-9]{20,}")


def events(client: httpx.Client, run_id: str) -> list[dict]:
    """Read the run's Server-Sent Events until `finished`."""
    found: list[dict] = []
    kind, data = None, []
    with client.stream("GET", f"/api/runs/{run_id}/events", timeout=30) as response:
        for line in response.iter_lines():
            if line.startswith("event:"):
                kind = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data.append(line.split(":", 1)[1].strip())
            elif not line and kind:
                found.append({"type": kind, "data": json.loads("\n".join(data))})
                if kind == "finished":
                    break
                kind, data = None, []
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_id")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    with httpx.Client(base_url=args.api, timeout=30) as client:

        def get(url: str, **params):
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()

        rid = args.run_id
        run = get(f"/api/runs/{rid}")
        if run["status"] != "SUCCESS":
            print(
                f"run {rid} is {run['status']}; record a successful run",
                file=sys.stderr,
            )
            return 1
        stream = events(client, rid)
        if not stream or stream[0]["type"] == "status":
            print("the event history is not in the API's memory any more", file=sys.stderr)
            return 1
        files = get(f"/api/runs/{rid}/files")
        recording = {
            "recorded_from": rid,
            "project": {
                k: v for k, v in get(f"/api/projects/{run['project_id']}").items() if k != "runs"
            },
            "run": run,
            "report": get(f"/api/runs/{rid}/report"),
            "files": files,
            "contents": {
                f["path"]: get(f"/api/runs/{rid}/files/content", path=f["path"])["content"]
                for f in files
                if "__pycache__" not in f["path"]
            },
            "reviews": get(f"/api/runs/{rid}/reviews"),
            "tests": get(f"/api/runs/{rid}/tests"),
            "git": get(f"/api/runs/{rid}/git"),
            "approvals": get(f"/api/runs/{rid}/approvals"),
            "events": stream,
        }
    recording["files"] = [f for f in files if "__pycache__" not in f["path"]]
    # Git dates carry the recording machine's time zone; a public recording uses UTC.
    for commit in recording["git"]["commits"]:
        commit["date"] = datetime.fromisoformat(commit["date"]).astimezone(UTC).isoformat()
    text = json.dumps(recording, indent=1, ensure_ascii=False)
    if SECRET_LIKE.search(text):
        print(
            "refusing to write: the recording contains a key-like string",
            file=sys.stderr,
        )
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(stream)} events, {len(recording['contents'])} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
