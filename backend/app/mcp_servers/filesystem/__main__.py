"""Start the Filesystem MCP server on stdio.

python -m app.mcp_servers.filesystem

Configuration comes only from environment variables passed by the parent process,
not from the shared .env, so the server never sees API keys:
    DEVTEAM_WORKSPACES_DIR   absolute path of the workspaces root (required)
    DEVTEAM_MAX_FILE_BYTES   optional size limit per file
    DEVTEAM_MAX_FILES        optional file count limit per workspace

stdout carries the MCP protocol, so logs go to stderr.
"""

import logging
import os
import sys
from pathlib import Path

from app.mcp_servers.filesystem.server import build_server


def _optional_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    return int(value) if value else None


def main() -> int:
    root = os.environ.get("DEVTEAM_WORKSPACES_DIR", "").strip()
    if not root or not Path(root).is_absolute():
        print("DEVTEAM_WORKSPACES_DIR must be set to an absolute path", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    server = build_server(
        Path(root),
        max_file_bytes=_optional_int("DEVTEAM_MAX_FILE_BYTES"),
        max_files=_optional_int("DEVTEAM_MAX_FILES"),
    )
    server.run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
