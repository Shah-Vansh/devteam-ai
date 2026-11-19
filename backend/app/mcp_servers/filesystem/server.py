"""Filesystem MCP server: four workspace-locked file tools.

Every tool returns one of two shapes as structured content:
    {"ok": true, "data": {...}}
    {"ok": false, "error_code": "PATH_ESCAPE", "message": "..."}

Rule violations are normal results (`ok: false`), not crashes, so the caller (workflow
code, or an agent through a read-only view) can react to the code. Only malformed calls,
such as a missing argument, come back as MCP protocol errors.

Annotations tell clients which tools only read. The backend additionally enforces that
agents may call only `read_file` and `list_files` (see `app/mcp_clients/filesystem.py`).
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from app.workspace.store import WorkspaceError, WorkspaceFiles

logger = logging.getLogger("app.mcp_servers.filesystem")

SERVER_NAME = "devteam-filesystem"
SERVER_VERSION = "0.1.0"

Workspace = Annotated[str, Field(description="Workspace name, e.g. todo-api-3f2a")]
RelPath = Annotated[str, Field(description="Relative file path with '/', e.g. app/main.py")]
Content = Annotated[str, Field(description="Full UTF-8 text content of the file")]

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
_CREATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
_UPDATE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)


def _run(tool: str, action: Callable[[], dict]) -> dict[str, Any]:
    try:
        data = action()
    except WorkspaceError as exc:
        logger.warning("tool_rejected tool=%s code=%s", tool, exc.code)
        return {"ok": False, "error_code": exc.code, "message": exc.message}
    except Exception:
        logger.exception("tool_failed tool=%s", tool)
        return {"ok": False, "error_code": "INTERNAL_ERROR", "message": "unexpected server error"}
    return {"ok": True, "data": data}


def build_server(
    workspaces_root: Path, *, max_file_bytes: int | None = None, max_files: int | None = None
) -> MCPServer:
    limits = {
        k: v for k, v in {"max_file_bytes": max_file_bytes, "max_files": max_files}.items() if v
    }
    store = WorkspaceFiles(workspaces_root, **limits)
    server = MCPServer(
        SERVER_NAME,
        version=SERVER_VERSION,
        instructions="File access limited to project workspaces. Paths are relative, use '/'.",
        log_level="WARNING",
    )

    @server.tool(annotations=_CREATE)
    def create_file(workspace: Workspace, path: RelPath, content: Content) -> dict[str, Any]:
        """Create a new file. Fails with FILE_EXISTS instead of overwriting."""
        return _run("create_file", lambda: store.create_file(workspace, path, content))

    @server.tool(annotations=_READ_ONLY)
    def read_file(workspace: Workspace, path: RelPath) -> dict[str, Any]:
        """Read a UTF-8 text file from the workspace."""
        return _run("read_file", lambda: store.read_file(workspace, path))

    @server.tool(annotations=_READ_ONLY)
    def list_files(workspace: Workspace) -> dict[str, Any]:
        """List all files in the workspace with their sizes."""
        return _run("list_files", lambda: store.list_files(workspace))

    @server.tool(annotations=_UPDATE)
    def update_file(workspace: Workspace, path: RelPath, content: Content) -> dict[str, Any]:
        """Replace the content of an existing file. Fails with FILE_NOT_FOUND if missing."""
        return _run("update_file", lambda: store.update_file(workspace, path, content))

    return server
