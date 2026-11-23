"""The HTTP API end to end: real FastAPI app, real migrations, real in-process MCP servers
and SQLite checkpoints; scripted LLM and executor. Runs proceed in the background, so
tests poll the run until it reaches the expected status."""

import threading
import time
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy import func, select

from app.agents.developer import Developer
from app.agents.planner import Planner
from app.agents.reviewer import Reviewer
from app.agents.tester import Tester
from app.api.main import create_app
from app.core.config import Settings
from app.db.models import Approval, GeneratedFile, LLMCall, Run
from app.db.session import Database
from app.execution.base import ExecutionResult
from app.gitops.approval import new_secret
from app.llm.fake import FakeLLMClient
from app.mcp_clients.filesystem import FilesystemClient
from app.mcp_clients.git import GitClient
from app.mcp_servers.filesystem.server import build_server
from app.mcp_servers.git.server import build_git_server
from app.services.runtime import Runtime
from app.workflow.graph import build_graph
from app.workflow.state import WorkflowDeps
from tests.conftest import code_changes, review_output

TESTS = {"tests/__init__.py": "", "tests/test_todos.py": "def test_ok():\n    assert True\n"}
REQUIREMENT = "Build a todo API with create, list and delete"


class ScriptedExecutor:
    name = "fake"

    def __init__(self, results):
        self.results = list(results)

    def run_tests(self, files, spec):
        return self.results.pop(0)


def passed():
    return ExecutionResult(status="PASSED", executor="fake", passed=3)


def run_responses(todo_plan_data, todo_files):
    """Planner, Developer, Reviewer, Tester: one valid answer each."""
    return [todo_plan_data, code_changes(todo_files), review_output(), code_changes(TESTS)]


def make_settings(tmp_path, **values) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        checkpoint_db_path=tmp_path / "checkpoints.db",
        workspaces_dir=tmp_path / "workspaces",
        **values,
    )


def runtime_factory(llm, executor, *, configured=True):
    @asynccontextmanager
    async def factory(settings: Settings):
        secret = new_secret()
        async with (
            AsyncSqliteSaver.from_conn_string(str(settings.checkpoint_db_path)) as saver,
            FilesystemClient(build_server(settings.workspaces_dir)) as fs,
            GitClient(
                build_git_server(settings.workspaces_dir, commit_secret=secret), secret=secret
            ) as git,
        ):

            def make_deps(progress):
                return WorkflowDeps(
                    planner=Planner(llm),
                    developer=Developer(llm),
                    reviewer=Reviewer(llm),
                    tester=Tester(llm),
                    executor=executor,
                    fs=fs,
                    git=git,
                    progress=progress,
                )

            yield Runtime(
                graph=build_graph().compile(checkpointer=saver),
                fs=fs,
                git=git,
                make_deps=make_deps if configured else None,
                executor_name=executor.name,
                model="fake-model",
                llm_error=None if configured else "LLM_API_KEY is not set in the root .env",
            )

    return factory


def client_for(tmp_path, responses, executor_results=(), **kw) -> TestClient:
    llm = FakeLLMClient(list(responses))
    factory = runtime_factory(llm, ScriptedExecutor(list(executor_results)), **kw)
    return TestClient(create_app(make_settings(tmp_path), runtime_factory=factory))


def wait_for(client, run_id, *statuses, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in statuses:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} stuck in {run['status']}, wanted {statuses}")


def start(client):
    project = client.post("/api/projects", json={"name": "todo", "requirement": REQUIREMENT})
    assert project.status_code == 201
    started = client.post(f"/api/projects/{project.json()['id']}/runs")
    assert started.status_code == 202
    return project.json()["id"], started.json()["run_id"]


def decide(client, run, decision="approve", **extra):
    approval_id = run["pending_approval"]["id"]
    return client.post(f"/api/approvals/{approval_id}", json={"decision": decision, **extra})


# ---------- basics ----------


def test_health_and_request_id(tmp_path):
    with client_for(tmp_path, []) as client:
        response = client.get("/api/health", headers={"X-Request-ID": "abc123"})
    assert response.status_code == 200
    assert response.json()["executor"] == "fake"
    assert response.json()["llm_configured"] is True
    assert response.headers["X-Request-ID"] == "abc123"


def test_projects_create_list_and_errors(tmp_path):
    with client_for(tmp_path, []) as client:
        created = client.post("/api/projects", json={"name": "todo", "requirement": REQUIREMENT})
        assert created.status_code == 201
        project_id = created.json()["id"]
        assert project_id.startswith("prj_")
        assert [p["id"] for p in client.get("/api/projects").json()] == [project_id]
        assert client.get(f"/api/projects/{project_id}").json()["runs"] == []

        invalid = client.post("/api/projects", json={"name": "", "requirement": "x"})
        assert invalid.status_code == 422
        assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
        assert invalid.json()["error"]["details"]["problems"][0]["field"] == "name"

        missing = client.get("/api/projects/prj_nope")
        assert missing.status_code == 404
        assert missing.json() == {
            "error": {
                "code": "PROJECT_NOT_FOUND",
                "message": "project prj_nope does not exist",
                "details": {},
            }
        }
        assert client.get("/api/runs/nope").json()["error"]["code"] == "RUN_NOT_FOUND"


def test_created_project_is_committed_before_the_response(tmp_path):
    # Found live: the session dependency committed after the response was sent, so the
    # next request could not find the project yet.
    with client_for(tmp_path, []) as client:
        created = client.post("/api/projects", json={"name": "t", "requirement": REQUIREMENT})
        db = Database(make_settings(tmp_path).database_url)  # a separate connection
        with db.session() as session:
            from app.db.models import Project

            assert session.get(Project, created.json()["id"]) is not None


def test_unconfigured_llm_refuses_to_start(tmp_path):
    with client_for(tmp_path, [], configured=False) as client:
        project = client.post("/api/projects", json={"name": "t", "requirement": REQUIREMENT})
        response = client.post(f"/api/projects/{project.json()['id']}/runs")
        assert client.get("/api/health").json()["llm_configured"] is False
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_NOT_CONFIGURED"


# ---------- a whole run over HTTP ----------


def test_full_run_with_two_approvals_ends_in_a_commit(tmp_path, todo_plan_data, todo_files):
    responses = run_responses(todo_plan_data, todo_files)
    with client_for(tmp_path, responses, [passed()]) as client:
        project_id, run_id = start(client)

        run = wait_for(client, run_id, "PAUSED")
        assert run["pending_approval"]["kind"] == "execute"
        assert client.post(f"/api/projects/{project_id}/runs").status_code == 409

        assert decide(client, run).status_code == 200
        run = wait_for(client, run_id, "PAUSED")
        assert run["pending_approval"]["kind"] == "commit"
        assert "tests/test_todos.py" in run["pending_approval"]["payload"]["files"]
        assert client.get(f"/api/runs/{run_id}/git").json()["initialized"] is False

        decide(client, run, message="First version of the todo API")
        run = wait_for(client, run_id, "SUCCESS")
        git_info = client.get(f"/api/runs/{run_id}/git").json()
        assert git_info["initialized"] and git_info["clean"] and git_info["branch"] == "main"
        assert git_info["commits"][0]["subject"] == "First version of the todo API"
        assert git_info["commits"][0]["commit"] == run["commit_sha"]

        reviews = client.get(f"/api/runs/{run_id}/reviews").json()
        tests = client.get(f"/api/runs/{run_id}/tests").json()
        approvals = client.get(f"/api/runs/{run_id}/approvals").json()
        files = client.get(f"/api/runs/{run_id}/files").json()
        content = client.get(f"/api/runs/{run_id}/files/content", params={"path": "app/main.py"})
        report = client.get(f"/api/runs/{run_id}/report").json()

    assert run["commit_sha"] and len(run["commit_sha"]) == 40
    assert run["llm_calls"] == 4 and run["review_status"] == "pass"
    assert [r["verdict"] for r in reviews] == ["pass"]
    assert tests[0]["status"] == "PASSED" and tests[0]["passed"] == 3
    assert [(a["kind"], a["status"]) for a in approvals] == [
        ("execute", "approved"),
        ("commit", "approved"),
    ]
    assert all("token_hash" not in a for a in approvals)
    assert {f["path"] for f in files} >= {"app/main.py", "tests/test_todos.py"}
    assert content.json()["content"] == todo_files["app/main.py"]
    assert [u["agent"] for u in report["usage_by_agent"]] == [
        "developer", "planner", "reviewer", "tester",
    ]  # fmt: skip
    assert [s["agent"] for s in report["steps"]][:3] == ["plan", "develop", "review"]
    assert report["steps"][-1]["agent"] == "commit"
    summaries = {s["agent"]: s["summary"] for s in report["steps"]}
    assert summaries["prepare_commit"] == ""  # found live: it repeated the previous line
    assert summaries["commit"].startswith("committed ")

    db = Database(make_settings(tmp_path).database_url)
    with db.session() as session:
        commit_approval = session.scalars(select(Approval).where(Approval.kind == "commit")).one()
        assert len(commit_approval.token_hash) == 64  # only a hash of the token is stored
        assert session.scalar(select(func.count()).select_from(LLMCall)) == 4
        assert session.scalar(select(func.count()).select_from(GeneratedFile)) == len(files)


def test_file_paths_are_checked_by_the_filesystem_server(tmp_path, todo_plan_data, todo_files):
    with client_for(tmp_path, run_responses(todo_plan_data, todo_files)) as client:
        _, run_id = start(client)
        wait_for(client, run_id, "PAUSED")
        bad = client.get(f"/api/runs/{run_id}/files/content", params={"path": "../../.env"})
        missing = client.get(f"/api/runs/{run_id}/files/content", params={"path": "nope.py"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_PATH"
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "FILE_NOT_FOUND"


def test_rejected_execution_and_double_decisions(tmp_path, todo_plan_data, todo_files):
    with client_for(tmp_path, run_responses(todo_plan_data, todo_files)) as client:
        _, run_id = start(client)
        run = wait_for(client, run_id, "PAUSED")
        assert decide(client, run, "reject").status_code == 200
        again = decide(client, run, "approve")
        run = wait_for(client, run_id, "NOT_EXECUTED")
    assert again.status_code == 400
    assert again.json()["error"]["code"] in ("APPROVAL_ALREADY_DECIDED", "RUN_NOT_PAUSED")
    assert run["error"] == "test execution was not approved"


def test_cancel_a_paused_run(tmp_path, todo_plan_data, todo_files):
    with client_for(tmp_path, run_responses(todo_plan_data, todo_files)) as client:
        _, run_id = start(client)
        wait_for(client, run_id, "PAUSED")
        assert client.post(f"/api/runs/{run_id}/cancel").status_code == 202
        run = wait_for(client, run_id, "CANCELLED")
        again = client.post(f"/api/runs/{run_id}/cancel")
        approvals = client.get(f"/api/runs/{run_id}/approvals").json()
    assert run["pending_approval"] is None
    assert approvals[0]["status"] == "cancelled"
    assert again.status_code == 400 and again.json()["error"]["code"] == "RUN_FINISHED"


class BlockingLLM(FakeLLMClient):
    """Blocks the first call until released, so a run can be cancelled mid-step."""

    def __init__(self):
        super().__init__([])
        self.release = threading.Event()

    def generate_structured(self, **kwargs):
        self.release.wait(10)
        raise RuntimeError("released")


def test_cancel_a_running_run(tmp_path):
    llm = BlockingLLM()
    factory = runtime_factory(llm, ScriptedExecutor([]))
    with TestClient(create_app(make_settings(tmp_path), runtime_factory=factory)) as client:
        _, run_id = start(client)
        time.sleep(0.3)  # the planner is now blocked inside its LLM call
        assert client.post(f"/api/runs/{run_id}/cancel").json()["status"] == "CANCELLING"
        run = wait_for(client, run_id, "CANCELLED")
        llm.release.set()
    assert run["error"] == "cancelled while running"


# ---------- events ----------


def test_event_stream_replays_a_finished_run(tmp_path, todo_plan_data, todo_files):
    with client_for(tmp_path, run_responses(todo_plan_data, todo_files)) as client:
        _, run_id = start(client)
        run = wait_for(client, run_id, "PAUSED")
        decide(client, run, "reject")
        wait_for(client, run_id, "NOT_EXECUTED")
        with client.stream("GET", f"/api/runs/{run_id}/events") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            text = "".join(response.iter_text())
    events = [line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("event: ")]
    assert events[0] == "log"
    assert "step" in events
    assert events.index("approval_required") < events.index("approval_decided")
    assert events[-1] == "finished"
    assert '"status": "NOT_EXECUTED"' in text


# ---------- restarts ----------


def test_paused_run_survives_an_api_restart(tmp_path, todo_plan_data, todo_files):
    with client_for(tmp_path, run_responses(todo_plan_data, todo_files)) as client:
        _, run_id = start(client)
        run = wait_for(client, run_id, "PAUSED")

    # A new API process: new runtime, new MCP servers, same databases.
    with client_for(tmp_path, [], [passed()]) as client:
        run = client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "PAUSED"
        decide(client, run)
        run = wait_for(client, run_id, "PAUSED")
        assert run["pending_approval"]["kind"] == "commit"
        decide(client, run)
        run = wait_for(client, run_id, "SUCCESS")
    assert run["commit_sha"]


def test_runs_active_during_a_crash_are_marked_on_startup(tmp_path):
    with client_for(tmp_path, []) as client:
        project = client.post("/api/projects", json={"name": "t", "requirement": REQUIREMENT})
    db = Database(make_settings(tmp_path).database_url)
    with db.session() as session:
        session.add(Run(id="20260101-000000-abcd", project_id=project.json()["id"]))
    with client_for(tmp_path, []) as client:
        run = client.get("/api/runs/20260101-000000-abcd").json()
    assert run["status"] == "ERROR"
    assert "stopped" in run["error"]


# ---------- migrations ----------


def test_migrations_match_the_models(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db.migrate import upgrade_database
    from app.db.models import Base

    url = make_settings(tmp_path).database_url
    upgrade_database(url)
    db = Database(url)
    with db.engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == []  # a model change without a migration would show up here


@pytest.fixture(autouse=True)
def _quiet_logs(caplog):
    caplog.set_level("ERROR")


def test_events_carry_the_time_they_happened():
    from app.services.events import EventBroker

    item = EventBroker().publish("run-1", "log", {"message": "planner: planning"})
    assert item.data["message"] == "planner: planning"
    assert item.data["at"].endswith("+00:00")  # UTC, ISO 8601
