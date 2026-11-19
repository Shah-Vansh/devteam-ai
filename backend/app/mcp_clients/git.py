"""Client for the Git MCP server. Held only by workflow code; agents never get it.

The client creates the token secret when it starts the server, passes it only to that
child process, and keeps it to sign approval tokens:

    async with GitClient.over_stdio(settings.workspaces_dir) as git:
        await git.initialize_repository(ws)
        token = git.issue_commit_token(ws, files)   # only after a human approved
        await git.create_commit(ws, "Initial version", token)
"""

import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self

from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver import MCPServer

from app.gitops.approval import content_digest, issue_token, new_secret
from app.gitops.repo import CommitAuthor
from app.mcp_clients.base import BACKEND_DIR, McpToolClient, ToolError

GIT_TOOLS = frozenset(
    {"initialize_repository", "get_git_status", "create_commit", "get_commit_history"}
)


class GitToolError(ToolError):
    """The Git server refused the operation, e.g. TOKEN_USED or CONTENT_CHANGED."""


def git_stdio_parameters(
    workspaces_dir: Path, secret: str, author: CommitAuthor | None = None
) -> StdioServerParameters:
    author = author or CommitAuthor()
    env = {
        "DEVTEAM_WORKSPACES_DIR": str(workspaces_dir.resolve()),
        "DEVTEAM_COMMIT_SECRET": secret,
        "DEVTEAM_COMMIT_AUTHOR_NAME": author.name,
        "DEVTEAM_COMMIT_AUTHOR_EMAIL": author.email,
        "PYTHONUTF8": "1",
    }
    return StdioServerParameters(
        command=sys.executable, args=["-m", "app.mcp_servers.git"], env=env, cwd=BACKEND_DIR
    )


class GitClient(McpToolClient):
    tools = GIT_TOOLS
    error_class = GitToolError

    def __init__(
        self,
        server: StdioServerParameters | MCPServer,
        *,
        secret: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        super().__init__(server, timeout_seconds=timeout_seconds)
        self._secret = secret

    @classmethod
    def over_stdio(cls, workspaces_dir: Path, author: CommitAuthor | None = None) -> Self:
        secret = new_secret()  # fresh per server start: old tokens stop working
        return cls(git_stdio_parameters(workspaces_dir, secret, author), secret=secret)

    def issue_commit_token(self, workspace: str, approved_digest: str) -> str:
        """Sign approval for the content the human saw (`files_digest` at approval time).
        Call only after a human approved; the server re-checks the digest against disk."""
        return issue_token(self._secret, workspace, approved_digest)

    async def initialize_repository(self, workspace: str) -> dict[str, Any]:
        return await self.call("initialize_repository", {"workspace": workspace})

    async def get_git_status(self, workspace: str) -> dict[str, Any]:
        return await self.call("get_git_status", {"workspace": workspace})

    async def create_commit(self, workspace: str, message: str, token: str) -> dict[str, Any]:
        return await self.call(
            "create_commit",
            {"workspace": workspace, "message": message, "approval_token": token},
        )

    async def get_commit_history(self, workspace: str, limit: int = 10) -> list[dict[str, Any]]:
        data = await self.call("get_commit_history", {"workspace": workspace, "limit": limit})
        return data["commits"]


def files_digest(files: Mapping[str, str]) -> str:
    """Digest of workspace files read through the Filesystem server (text, UTF-8), equal to
    the digest the Git server computes from the same files' bytes on disk."""
    return content_digest({p: c.encode("utf-8") for p, c in files.items()})
