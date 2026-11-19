"""Client for the Filesystem MCP server.

Normal use starts the server as a child process and talks to it over stdio:

    async with FilesystemClient.over_stdio(settings.workspaces_dir) as fs:
        await fs.create_file("todo-api", "app/main.py", "...")

Tests can pass an `MCPServer` instance instead, which connects in-process.

Two permission levels:
- `FilesystemClient` can call every tool. Only workflow code holds one.
- `ReadOnlyFilesystem` exposes `read_file` and `list_files` only. This is what an
  agent gets, so even a prompt-injected model cannot write files (ADR 0004).
"""

import sys
from pathlib import Path
from typing import Any, Self

from mcp.client.stdio import StdioServerParameters
from mcp.types import Tool

from app.mcp_clients.base import (  # noqa: F401 - re-exported for existing imports
    BACKEND_DIR,
    McpCallError,
    McpToolClient,
    ToolError,
    ToolNotAllowedError,
)

ALL_TOOLS = frozenset({"create_file", "read_file", "list_files", "update_file"})
READ_ONLY_TOOLS = frozenset({"read_file", "list_files"})


class FilesystemToolError(ToolError):
    """The Filesystem server refused the operation, e.g. PATH_ESCAPE."""


def stdio_parameters(
    workspaces_dir: Path, *, max_file_bytes: int | None = None, max_files: int | None = None
) -> StdioServerParameters:
    """How to start the server. Only the variables it needs are passed; the MCP SDK adds a
    small safe set (PATH, SYSTEMROOT, ...) and nothing else, so API keys never reach it."""
    env = {"DEVTEAM_WORKSPACES_DIR": str(workspaces_dir.resolve()), "PYTHONUTF8": "1"}
    if max_file_bytes:
        env["DEVTEAM_MAX_FILE_BYTES"] = str(max_file_bytes)
    if max_files:
        env["DEVTEAM_MAX_FILES"] = str(max_files)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_servers.filesystem"],
        env=env,
        cwd=BACKEND_DIR,
    )


class FilesystemClient(McpToolClient):
    tools = ALL_TOOLS
    error_class = FilesystemToolError

    @classmethod
    def over_stdio(cls, workspaces_dir: Path, **limits: int | None) -> Self:
        return cls(stdio_parameters(workspaces_dir, **limits))

    async def create_file(self, workspace: str, path: str, content: str) -> dict[str, Any]:
        return await self.call(
            "create_file", {"workspace": workspace, "path": path, "content": content}
        )

    async def read_file(self, workspace: str, path: str) -> str:
        data = await self.call("read_file", {"workspace": workspace, "path": path})
        return data["content"]

    async def list_files(self, workspace: str) -> list[str]:
        data = await self.call("list_files", {"workspace": workspace})
        return [entry["path"] for entry in data["files"]]

    async def update_file(self, workspace: str, path: str, content: str) -> dict[str, Any]:
        return await self.call(
            "update_file", {"workspace": workspace, "path": path, "content": content}
        )

    def read_only(self) -> "ReadOnlyFilesystem":
        return ReadOnlyFilesystem(self)


class ReadOnlyFilesystem:
    """Same connection, fewer powers. Has no write methods at all, and `call` rejects
    write tools by name, so a tool name chosen by an LLM cannot get around it."""

    def __init__(self, inner: FilesystemClient) -> None:
        self._inner = inner

    async def list_tools(self) -> list[Tool]:
        return [t for t in await self._inner.list_tools() if t.name in READ_ONLY_TOOLS]

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in READ_ONLY_TOOLS:
            raise ToolNotAllowedError(f"tool {name!r} is not allowed for this caller")
        return await self._inner.call(name, arguments)

    async def read_file(self, workspace: str, path: str) -> str:
        return await self._inner.read_file(workspace, path)

    async def list_files(self, workspace: str) -> list[str]:
        return await self._inner.list_files(workspace)
