"""Reading and writing a run's workspace through the Filesystem MCP client."""

import secrets

from app.mcp_clients.filesystem import FilesystemClient, FilesystemToolError
from app.schemas.code import CodeChanges
from app.schemas.testing import TestSuite, is_test_path


def new_workspace_name(project_name: str) -> str:
    """Unique folder per run: `<project>-<6 hex chars>`, at most 64 characters."""
    base = project_name[:50].strip("-") or "project"
    return f"{base}-{secrets.token_hex(3)}"


async def write_changes(
    fs: FilesystemClient, workspace: str, changes: CodeChanges | TestSuite
) -> list[str]:
    """Create new files, update existing ones. The workspace is created by the first write."""
    try:
        existing = set(await fs.list_files(workspace))
    except FilesystemToolError as exc:
        if exc.code != "WORKSPACE_NOT_FOUND":
            raise
        existing = set()
    for change in changes.files:
        if change.path in existing:
            await fs.update_file(workspace, change.path, change.content)
        else:
            await fs.create_file(workspace, change.path, change.content)
    return [c.path for c in changes.files]


async def read_all(fs: FilesystemClient, workspace: str) -> dict[str, str]:
    return {p: await fs.read_file(workspace, p) for p in await fs.list_files(workspace)}


def split_files(files: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """(application files, test files)."""
    tests = {p: c for p, c in files.items() if is_test_path(p)}
    return {p: c for p, c in files.items() if p not in tests}, tests
