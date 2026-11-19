"""The Filesystem MCP server and client, end to end.

Most tests connect in-process (fast). The `stdio` tests start the real server as a
child process, exactly as the backend will.
"""

import subprocess
import sys

import pytest

from app.mcp_clients.filesystem import (
    BACKEND_DIR,
    FilesystemClient,
    FilesystemToolError,
    McpCallError,
    ReadOnlyFilesystem,
    ToolNotAllowedError,
    stdio_parameters,
)
from app.mcp_servers.filesystem.server import build_server

pytestmark = pytest.mark.anyio
WS = "demo"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def root(tmp_path):
    return tmp_path / "workspaces"


@pytest.fixture
def server(root):
    return build_server(root, max_file_bytes=1000)


async def test_lists_four_tools_with_schemas_and_annotations(server):
    async with FilesystemClient(server) as fs:
        tools = {tool.name: tool for tool in await fs.list_tools()}

    assert set(tools) == {"create_file", "read_file", "list_files", "update_file"}
    schema = tools["create_file"].input_schema
    assert set(schema["required"]) == {"workspace", "path", "content"}
    assert "Relative file path" in schema["properties"]["path"]["description"]
    assert tools["read_file"].annotations.read_only_hint is True
    assert tools["list_files"].annotations.read_only_hint is True
    assert tools["create_file"].annotations.read_only_hint is False
    assert tools["update_file"].annotations.destructive_hint is True


async def test_create_read_list_update(server, root):
    async with FilesystemClient(server) as fs:
        created = await fs.create_file(WS, "app/main.py", "print('hi')\n")
        assert created == {"path": "app/main.py", "size_bytes": 12}
        await fs.create_file(WS, "requirements.txt", "fastapi\n")
        assert await fs.read_file(WS, "app/main.py") == "print('hi')\n"
        assert await fs.list_files(WS) == ["app/main.py", "requirements.txt"]
        await fs.update_file(WS, "app/main.py", "print('bye')\n")
        assert await fs.read_file(WS, "app/main.py") == "print('bye')\n"
    assert (root / WS / "app" / "main.py").read_text() == "print('bye')\n"


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("../escape.py", "INVALID_PATH"),
        ("C:/Windows/win.ini", "INVALID_PATH"),
        ("nul.py", "INVALID_PATH"),
        ("tool.exe", "EXTENSION_NOT_ALLOWED"),
    ],
)
async def test_rule_violations_come_back_as_error_codes(server, root, path, code):
    async with FilesystemClient(server) as fs:
        with pytest.raises(FilesystemToolError) as info:
            await fs.create_file(WS, path, "x")
    assert info.value.code == code
    assert not (root.parent / "escape.py").exists()


async def test_existing_file_is_not_overwritten(server):
    async with FilesystemClient(server) as fs:
        await fs.create_file(WS, "a.py", "one")
        with pytest.raises(FilesystemToolError) as info:
            await fs.create_file(WS, "a.py", "two")
        assert info.value.code == "FILE_EXISTS"
        assert await fs.read_file(WS, "a.py") == "one"


async def test_size_limit_is_enforced_by_the_server(server):
    async with FilesystemClient(server) as fs:
        with pytest.raises(FilesystemToolError) as info:
            await fs.create_file(WS, "big.py", "x" * 1001)
    assert info.value.code == "FILE_TOO_LARGE"


async def test_malformed_call_is_a_protocol_error(server):
    async with FilesystemClient(server) as fs:
        with pytest.raises(McpCallError):
            await fs.call("read_file", {"workspace": WS})  # missing "path"


async def test_unknown_tool_is_refused_before_sending(server):
    async with FilesystemClient(server) as fs:
        with pytest.raises(ToolNotAllowedError):
            await fs.call("delete_everything", {})


async def test_read_only_view_cannot_write(server, root):
    async with FilesystemClient(server) as fs:
        await fs.create_file(WS, "a.py", "original")
        agent_view = fs.read_only()
        assert isinstance(agent_view, ReadOnlyFilesystem)
        assert not hasattr(agent_view, "create_file")
        assert not hasattr(agent_view, "update_file")
        assert {t.name for t in await agent_view.list_tools()} == {"read_file", "list_files"}

        for name in ("create_file", "update_file"):
            with pytest.raises(ToolNotAllowedError):
                await agent_view.call(name, {"workspace": WS, "path": "a.py", "content": "pwned"})

        assert await agent_view.read_file(WS, "a.py") == "original"
        data = await agent_view.call("list_files", {"workspace": WS})
        assert data["files"][0]["path"] == "a.py"
    assert (root / WS / "a.py").read_text() == "original"


# ---------- real child process over stdio ----------


async def test_stdio_round_trip(root):
    async with FilesystemClient.over_stdio(root, max_file_bytes=500) as fs:
        assert len(await fs.list_tools()) == 4
        await fs.create_file(WS, "app/main.py", "from fastapi import FastAPI\n")
        assert await fs.read_file(WS, "app/main.py") == "from fastapi import FastAPI\n"
        with pytest.raises(FilesystemToolError) as info:
            await fs.create_file(WS, "big.py", "x" * 501)
        assert info.value.code == "FILE_TOO_LARGE"
    assert (root / WS / "app" / "main.py").is_file()


def test_server_receives_only_the_variables_it_needs(root, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "gsk_should_not_leak")
    params = stdio_parameters(root, max_files=7)
    assert set(params.env) == {"DEVTEAM_WORKSPACES_DIR", "DEVTEAM_MAX_FILES", "PYTHONUTF8"}
    assert params.env["DEVTEAM_WORKSPACES_DIR"] == str(root.resolve())
    assert params.args == ["-m", "app.mcp_servers.filesystem"]


def test_server_refuses_to_start_without_workspaces_root():
    env = {k: v for k, v in __import__("os").environ.items() if k != "DEVTEAM_WORKSPACES_DIR"}
    proc = subprocess.run(  # noqa: S603 - fixed arguments, our own module
        [sys.executable, "-m", "app.mcp_servers.filesystem"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 2
    assert "DEVTEAM_WORKSPACES_DIR" in proc.stderr


class BoomError(Exception):
    pass


async def test_errors_inside_the_block_keep_their_type(server):
    # Without unwrapping, the SDK's task group turns this into an ExceptionGroup and
    # `except BoomError` in callers would never match.
    with pytest.raises(BoomError):
        async with FilesystemClient(server) as fs:
            await fs.list_tools()
            raise BoomError("raised by caller code")


async def test_errors_inside_the_block_keep_their_type_over_stdio(root):
    with pytest.raises(BoomError):
        async with FilesystemClient.over_stdio(root) as fs:
            await fs.list_tools()
            raise BoomError("raised by caller code")
