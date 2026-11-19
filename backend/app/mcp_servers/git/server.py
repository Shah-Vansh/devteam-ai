"""Git MCP server: repository tools for workspaces, commits only with an approval token.

Same result shape as the Filesystem server: `{"ok": true, "data": ...}` or
`{"ok": false, "error_code": ..., "message": ...}`. There is no push, remote or
branch-switching tool: the server can only record local history of a workspace.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from app.gitops.repo import CommitAuthor, GitError, GitRepos
from app.workspace.store import WorkspaceFiles

logger = logging.getLogger("app.mcp_servers.git")

SERVER_NAME = "devteam-git"
SERVER_VERSION = "0.1.0"
SECURITY_CODES = frozenset(
    {"TOKEN_MISSING", "TOKEN_INVALID", "TOKEN_EXPIRED", "TOKEN_USED", "TOKEN_WRONG_WORKSPACE"}
)

Workspace = Annotated[str, Field(description="Workspace name, e.g. todo-api-3f2a")]

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
_WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)


def _run(tool: str, action: Callable[[], dict]) -> dict[str, Any]:
    try:
        data = action()
    except GitError as exc:
        # A refused token may mean an attempt to commit without approval.
        level = logging.WARNING if exc.code in SECURITY_CODES else logging.INFO
        logger.log(level, "tool_rejected tool=%s code=%s", tool, exc.code)
        return {"ok": False, "error_code": exc.code, "message": exc.message}
    except Exception:
        logger.exception("tool_failed tool=%s", tool)
        return {"ok": False, "error_code": "INTERNAL_ERROR", "message": "unexpected server error"}
    return {"ok": True, "data": data}


def build_git_server(
    workspaces_root: Path, *, commit_secret: str, author: CommitAuthor | None = None
) -> MCPServer:
    repos = GitRepos(WorkspaceFiles(workspaces_root), commit_secret=commit_secret, author=author)
    server = MCPServer(
        SERVER_NAME,
        version=SERVER_VERSION,
        instructions="Local git history for project workspaces. Commits need an approval token.",
        log_level="WARNING",
    )

    @server.tool(annotations=_WRITE)
    def initialize_repository(workspace: Workspace) -> dict[str, Any]:
        """Create a git repository in the workspace (no-op if it already has one)."""
        return _run("initialize_repository", lambda: repos.initialize_repository(workspace))

    @server.tool(annotations=_READ_ONLY)
    def get_git_status(workspace: Workspace) -> dict[str, Any]:
        """Branch and changed or untracked files."""
        return _run("get_git_status", lambda: repos.get_git_status(workspace))

    @server.tool(annotations=_WRITE)
    def create_commit(
        workspace: Workspace,
        message: Annotated[str, Field(description="Commit message; first line at most 100 chars")],
        approval_token: Annotated[
            str, Field(description="One-time token issued by the backend after human approval")
        ],
    ) -> dict[str, Any]:
        """Commit all current files. Refused without a valid, unused approval token for
        exactly the current content of this workspace."""
        return _run(
            "create_commit", lambda: repos.create_commit(workspace, message, approval_token)
        )

    @server.tool(annotations=_READ_ONLY)
    def get_commit_history(
        workspace: Workspace,
        limit: Annotated[int, Field(description="Number of commits, 1 to 50")] = 10,
    ) -> dict[str, Any]:
        """Most recent commits, newest first."""
        return _run("get_commit_history", lambda: repos.get_commit_history(workspace, limit))

    return server
