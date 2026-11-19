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
from types import TracebackType
from typing import Any, Self

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver import MCPServer
from mcp.types import Tool

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALL_TOOLS = frozenset({"create_file", "read_file", "list_files", "update_file"})
READ_ONLY_TOOLS = frozenset({"read_file", "list_files"})


class FilesystemToolError(Exception):
    """The server refused the operation (`ok: false`), e.g. PATH_ESCAPE."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class McpCallError(Exception):
    """The call itself failed: bad arguments, unknown tool, or a broken connection."""


class ToolNotAllowedError(Exception):
    """The caller tried a tool outside its permission set. Checked before any I/O."""


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


class FilesystemClient:
    def __init__(
        self, server: StdioServerParameters | MCPServer, *, timeout_seconds: float = 30.0
    ) -> None:
        self._client = Client(server, read_timeout_seconds=timeout_seconds)
        self._allowed = ALL_TOOLS

    @classmethod
    def over_stdio(cls, workspaces_dir: Path, **limits: int | None) -> Self:
        return cls(stdio_parameters(workspaces_dir, **limits))

    async def __aenter__(self) -> Self:
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            await self._client.__aexit__(exc_type, exc, tb)
        except BaseExceptionGroup as group:
            # The SDK's task group wraps an error raised inside `async with` in an
            # ExceptionGroup. Re-raise the original so callers can catch it by type.
            if exc is not None and _contains(group, exc):
                raise exc from None
            raise

    # ---------- discovery ----------

    async def list_tools(self) -> list[Tool]:
        """Tools the server offers that this client may call, with their JSON schemas."""
        result = await self._client.list_tools()
        return [tool for tool in result.tools if tool.name in self._allowed]

    # ---------- calls ----------

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self._allowed:
            raise ToolNotAllowedError(f"tool {name!r} is not allowed for this caller")
        try:
            result = await self._client.call_tool(name, arguments)
        except Exception as exc:
            raise McpCallError(f"{name} failed: {exc}") from exc
        if result.is_error or not isinstance(result.structured_content, dict):
            text = " ".join(getattr(part, "text", "") for part in result.content)
            raise McpCallError(f"{name} failed: {text.strip() or 'no structured result'}")

        payload = result.structured_content
        if not payload.get("ok"):
            raise FilesystemToolError(
                str(payload.get("error_code", "UNKNOWN")), str(payload.get("message", ""))
            )
        return payload["data"]

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


def _contains(group: BaseExceptionGroup, target: BaseException) -> bool:
    return any(
        item is target or (isinstance(item, BaseExceptionGroup) and _contains(item, target))
        for item in group.exceptions
    )


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
