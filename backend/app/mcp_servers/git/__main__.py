"""Start the Git MCP server on stdio.

python -m app.mcp_servers.git

Configuration only from variables the parent process passes (never the shared .env):
    DEVTEAM_WORKSPACES_DIR      absolute path of the workspaces root (required)
    DEVTEAM_COMMIT_SECRET       hex secret for approval tokens (required; created per start)
    DEVTEAM_COMMIT_AUTHOR_NAME  optional author name for commits
    DEVTEAM_COMMIT_AUTHOR_EMAIL optional author email for commits
"""

import logging
import os
import sys
from pathlib import Path

from app.gitops.repo import CommitAuthor
from app.mcp_servers.git.server import build_git_server


def main() -> int:
    root = os.environ.get("DEVTEAM_WORKSPACES_DIR", "").strip()
    secret = os.environ.get("DEVTEAM_COMMIT_SECRET", "").strip()
    if not root or not Path(root).is_absolute():
        print("DEVTEAM_WORKSPACES_DIR must be set to an absolute path", file=sys.stderr)
        return 2
    if len(secret) < 64:
        print("DEVTEAM_COMMIT_SECRET must be set (64 hex characters)", file=sys.stderr)
        return 2
    author = CommitAuthor()
    author.name = os.environ.get("DEVTEAM_COMMIT_AUTHOR_NAME") or author.name
    author.email = os.environ.get("DEVTEAM_COMMIT_AUTHOR_EMAIL") or author.email
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    build_git_server(Path(root), commit_secret=secret, author=author).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
