"""What every client of our MCP servers shares: connecting (stdio or in-process),
a per-client allow-list of tools, and turning results into data or typed errors.

Every server tool returns `{"ok": true, "data": ...}` or
`{"ok": false, "error_code": ..., "message": ...}`; the latter becomes the client's
`ToolError` subclass so callers can react to the code.
"""

from pathlib import Path
from types import TracebackType
from typing import Any, ClassVar, Self

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.server.mcpserver import MCPServer
from mcp.types import Tool

BACKEND_DIR = Path(__file__).resolve().parents[2]


class ToolError(Exception):
    """The server refused the operation (`ok: false`)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class McpCallError(Exception):
    """The call itself failed: bad arguments, unknown tool, or a broken connection."""


class ToolNotAllowedError(Exception):
    """The caller tried a tool outside its permission set. Checked before any I/O."""


class McpToolClient:
    tools: ClassVar[frozenset[str]] = frozenset()
    error_class: ClassVar[type[ToolError]] = ToolError

    def __init__(
        self, server: StdioServerParameters | MCPServer, *, timeout_seconds: float = 30.0
    ) -> None:
        self._client = Client(server, read_timeout_seconds=timeout_seconds)

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

    async def list_tools(self) -> list[Tool]:
        """Tools the server offers that this client may call, with their JSON schemas."""
        result = await self._client.list_tools()
        return [tool for tool in result.tools if tool.name in self.tools]

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self.tools:
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
            raise self.error_class(
                str(payload.get("error_code", "UNKNOWN")), str(payload.get("message", ""))
            )
        return payload["data"]


def _contains(group: BaseExceptionGroup, target: BaseException) -> bool:
    return any(
        item is target or (isinstance(item, BaseExceptionGroup) and _contains(item, target))
        for item in group.exceptions
    )
