"""Security checks that span modules, and failure scenarios.

Each test names the threat it covers (docs/SECURITY_DESIGN.md). Threats already covered
elsewhere are listed in docs/SECURITY_DESIGN.md under "Security tests".
"""

import inspect

import pytest
from e2b import SandboxException

from app.agents.developer import Developer
from app.agents.planner import Planner
from app.agents.reviewer import Reviewer
from app.agents.tester import Tester
from app.core.config import Settings
from app.execution.base import ExecutionSpec
from app.execution.e2b_executor import E2BExecutor
from app.mcp_clients.filesystem import McpCallError, ReadOnlyFilesystem, stdio_parameters
from app.mcp_clients.git import git_stdio_parameters
from app.schemas.plan import ProjectPlan

SECRET = "gsk_" + "s3cr3t" * 8


# ---------- T3: agents cannot write, commit or run anything ----------


@pytest.mark.parametrize("agent", [Planner, Developer, Tester])
def test_agents_are_built_from_an_llm_only(agent):
    # No filesystem, git client or executor is ever handed to these agents, so even a
    # fully prompt-injected model has nothing to write, commit or execute with.
    assert list(inspect.signature(agent.__init__).parameters) == ["self", "llm"]


def test_reviewer_only_ever_receives_the_read_only_view():
    hint = inspect.signature(Reviewer.review).parameters["fs"].annotation
    assert hint is ReadOnlyFilesystem
    assert not hasattr(ReadOnlyFilesystem, "create_file")
    assert not hasattr(ReadOnlyFilesystem, "update_file")


def test_injected_paths_in_a_plan_are_rejected(todo_plan_data):
    # A requirement saying "also write ../../.ssh/authorized_keys" cannot get that path
    # through the plan schema, whatever the model was talked into.
    todo_plan_data["files"].append({"path": "../../.ssh/authorized_keys.txt", "purpose": "x"})
    with pytest.raises(ValueError):
        ProjectPlan.model_validate(todo_plan_data)


# ---------- T5: secrets stay in the backend process ----------


def test_mcp_servers_get_no_api_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", SECRET)
    monkeypatch.setenv("E2B_API_KEY", SECRET)
    for params in (stdio_parameters(tmp_path), git_stdio_parameters(tmp_path, "ab" * 32)):
        assert SECRET not in str(params.env)
        assert not any("API_KEY" in key for key in params.env)


def test_health_endpoint_never_shows_keys(tmp_path):
    from fastapi.testclient import TestClient

    from app.api.main import create_app
    from tests.test_api import ScriptedExecutor, make_settings, runtime_factory

    settings = make_settings(tmp_path, llm_api_key=SECRET, e2b_api_key=SECRET)
    factory = runtime_factory(None, ScriptedExecutor([]))
    with TestClient(create_app(settings, runtime_factory=factory)) as client:
        body = client.get("/api/health").text
        missing = client.get("/api/runs/nope").text
    assert SECRET not in body and SECRET not in missing


def test_settings_hide_keys_in_repr():
    settings = Settings(_env_file=None, llm_api_key=SECRET)
    assert SECRET not in repr(settings)
    assert SECRET not in str(settings.model_dump())


# ---------- T11: the local API is not open to other websites ----------


def test_api_binds_to_localhost_by_default():
    assert Settings(_env_file=None).backend_host == "127.0.0.1"


def test_cors_allows_only_the_dashboard(tmp_path):
    from fastapi.testclient import TestClient

    from app.api.main import create_app
    from tests.test_api import ScriptedExecutor, make_settings, runtime_factory

    settings = make_settings(tmp_path, cors_origins="http://localhost:5173")
    factory = runtime_factory(None, ScriptedExecutor([]))
    with TestClient(create_app(settings, runtime_factory=factory)) as client:
        good = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
        evil = client.get("/api/health", headers={"Origin": "https://evil.example"})
        preflight = client.options(
            "/api/projects",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert good.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in evil.headers
    assert preflight.status_code == 400  # the browser blocks the cross-site POST


def test_api_offers_no_way_to_write_files_or_commit_directly(tmp_path):
    from app.api.main import create_app

    app = create_app(Settings(_env_file=None))
    # The OpenAPI schema is the API's published surface (included routers included).
    writes = {
        (path, method.upper())
        for path, operations in app.openapi()["paths"].items()
        for method in operations
        if method in ("post", "put", "patch", "delete")
    }
    # Only these change anything; commits happen solely through an approval.
    assert writes == {
        ("/api/projects", "POST"),
        ("/api/projects/{project_id}/runs", "POST"),
        ("/api/runs/{run_id}/cancel", "POST"),
        ("/api/approvals/{approval_id}", "POST"),
    }


# ---------- failure scenarios ----------


def test_unreachable_sandbox_is_an_error_not_a_pass():
    def factory(**_kwargs):
        raise SandboxException("connection refused")

    result = E2BExecutor("key", sandbox_factory=factory).run_tests(
        {"app/main.py": "x = 1\n"}, ExecutionSpec()
    )
    assert result.status == "ERROR"
    assert "sandbox error" in result.detail
    assert result.passed == 0


@pytest.mark.anyio
async def test_a_dead_mcp_server_ends_the_run_as_error(tmp_path, todo_plan_data, todo_files):
    """The Filesystem server process dies in the middle of a run: the run must end in a
    defined state with a reason, not hang or crash the caller."""
    from app.gitops.approval import new_secret
    from app.mcp_servers.filesystem.server import build_server
    from app.mcp_servers.git.server import build_git_server
    from tests.conftest import code_changes, review_output
    from tests.test_workflow import Harness, ScriptedExecutor, Servers, clients

    root = tmp_path / "workspaces"
    secret = new_secret()
    servers = Servers(build_server(root), build_git_server(root, commit_secret=secret), secret)
    async with clients(servers) as (fs, git):

        async def dead(*_args, **_kwargs):
            raise McpCallError("create_file failed: connection closed")

        fs.call = dead  # every tool call now fails, as after a crash
        h = Harness(fs, git, [code_changes(todo_files), review_output()], ScriptedExecutor([]))
        step = await h.start(plan=todo_plan_data)
    assert step.finished
    assert step.state["status"] == "ERROR"
    assert "workspace error" in step.state["stop_reason"]


@pytest.fixture
def anyio_backend():
    return "asyncio"
