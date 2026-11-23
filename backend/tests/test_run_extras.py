"""Download as ZIP, "Try the API" previews and the daily token estimate, over HTTP; and
the preview sandbox steps with a stand-in for the E2B SDK."""

import io
import time
import zipfile

import pytest
from e2b import CommandExitException

from app.execution.preview import E2BPreview, PreviewError, PreviewHandle, install_list
from tests.test_api import client_for, decide, passed, run_responses, start, wait_for


def successful_run(client):
    _, run_id = start(client)
    run = wait_for(client, run_id, "PAUSED")
    decide(client, run)
    run = wait_for(client, run_id, "PAUSED")
    decide(client, run)
    wait_for(client, run_id, "SUCCESS")
    return run_id


class FakePreview:
    """Stands in for E2BPreview: records what it was asked to start."""

    def __init__(self):
        self.started: list[dict[str, str]] = []
        self.killed = 0

    def start(self, files):
        self.started.append(files)
        return PreviewHandle(
            url="https://8000-sbx.example.test", expires_at=time.time() + 600, sandbox=self
        )

    def kill(self):
        self.killed += 1


def test_download_preview_and_usage(tmp_path, todo_plan_data, todo_files):
    preview = FakePreview()
    responses = run_responses(todo_plan_data, todo_files)
    with client_for(
        tmp_path, responses, [passed()], preview=preview, daily_token_limit=200_000
    ) as client:
        run_id = successful_run(client)
        run = client.get(f"/api/runs/{run_id}").json()

        archive = client.get(f"/api/runs/{run_id}/archive")
        assert client.get("/api/health").json()["preview_available"] is True
        assert client.get(f"/api/runs/{run_id}/preview").json()["status"] == "stopped"
        started = client.post(f"/api/runs/{run_id}/preview").json()
        again = client.post(f"/api/runs/{run_id}/preview").json()
        running = client.get(f"/api/runs/{run_id}/preview").json()
        stopped = client.post(f"/api/runs/{run_id}/preview/stop").json()
        usage = client.get("/api/usage").json()

    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    assert f'filename="{run["workspace"]}.zip"' in archive.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(archive.content)).namelist()
    assert f"{run['workspace']}/app/main.py" in names
    assert f"{run['workspace']}/tests/test_todos.py" in names
    assert not any("/.git/" in n for n in names)

    assert started["status"] == "running" and started["url"] == "https://8000-sbx.example.test"
    assert started["expires_at"]
    assert again == started and len(preview.started) == 1  # one preview per run
    assert "app/main.py" in preview.started[0]
    assert running["status"] == "running"
    assert stopped["status"] == "stopped" and preview.killed == 1

    used = run["input_tokens"] + run["output_tokens"]
    assert usage["tokens_used"] == used and used > 0
    assert usage["daily_limit"] == 200_000 and usage["tokens_left"] == 200_000 - used
    assert usage["typical_run_tokens"] == used


def test_preview_needs_passed_tests(tmp_path, todo_plan_data, todo_files):
    with client_for(tmp_path, run_responses(todo_plan_data, todo_files)) as client:
        _, run_id = start(client)
        wait_for(client, run_id, "PAUSED")  # tests not run yet
        refused = client.post(f"/api/runs/{run_id}/preview")
        usage = client.get("/api/usage").json()
        assert client.get("/api/health").json()["preview_available"] is False
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "PREVIEW_NOT_ALLOWED"
    assert usage["daily_limit"] == 0 and usage["tokens_left"] is None


def test_preview_unavailable_without_a_sandbox(tmp_path, todo_plan_data, todo_files):
    responses = run_responses(todo_plan_data, todo_files)
    with client_for(tmp_path, responses, [passed()]) as client:
        run_id = successful_run(client)
        response = client.post(f"/api/runs/{run_id}/preview")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PREVIEW_UNAVAILABLE"


def test_archive_of_an_unknown_run(tmp_path):
    with client_for(tmp_path, []) as client:
        missing = client.get("/api/runs/nope/archive")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RUN_NOT_FOUND"


# ---------- the sandbox steps, with a stand-in SDK ----------


def exit_error(stderr: str) -> CommandExitException:
    return CommandExitException(stdout="", stderr=stderr, exit_code=1, error="")


class FakeCommands:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.fail_install = False
        self.down_for = 0  # probes that fail before the server answers

    def run(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        if cmd.startswith("pip install") and self.fail_install:
            raise exit_error("no matching distribution")
        if "urlopen" in cmd and self.down_for > 0:
            self.down_for -= 1
            raise exit_error("connection refused")


class FakeSandbox:
    def __init__(self):
        self.created_with: dict = {}
        self.files_written: dict[str, str] = {}
        self.files = self
        self.commands = FakeCommands()
        self.network_updates: list[dict] = []
        self.killed = False
        self.timeout = None

    def write(self, path, content):
        self.files_written[path] = content

    def update_network(self, update):
        self.network_updates.append(update)
        self.commands.calls.append(("<network update>", update))

    def set_timeout(self, seconds):
        self.timeout = seconds

    def get_host(self, port):
        return f"{port}-sbx.e2b.app"

    def kill(self):
        self.killed = True


FILES = {
    "app/__init__.py": "",
    "app/main.py": "from fastapi import FastAPI\napp = FastAPI()\n",
    "requirements.txt": "fastapi\npytest\nrequests\n",
}


def make_preview(sandbox):
    def factory(**kwargs):
        sandbox.created_with = kwargs
        return sandbox

    return E2BPreview("key", "fastapi==1\n", sandbox_factory=factory, minutes=5)


def test_preview_runs_the_app_with_internet_off_and_no_secrets(monkeypatch):
    sandbox = FakeSandbox()
    handle = make_preview(sandbox).start(FILES)

    assert handle.url == "https://8000-sbx.e2b.app"
    assert "envs" not in sandbox.created_with  # nothing from the host's environment
    assert sandbox.created_with["network"] == {"allow_public_traffic": True}
    assert set(sandbox.files_written) == {
        "/home/user/project/app/__init__.py",
        "/home/user/project/app/main.py",
        "/home/user/project/requirements.txt",
        "/home/user/constraints.txt",
    }
    commands = [c for c, _ in sandbox.commands.calls]
    install = commands[0]
    assert install.startswith("pip install") and "-c /home/user/constraints.txt" in install
    assert "fastapi" in install and "uvicorn" in install
    assert "pytest" not in install and "requests" not in install  # test-only / not allowed
    assert sandbox.network_updates == [{"allow_internet_access": False}]
    server = next(kw for c, kw in sandbox.commands.calls if "uvicorn app.main:app" in c)
    assert server["background"] is True
    # internet goes off after installing and before the generated code starts
    server_index = next(i for i, c in enumerate(commands) if c.startswith("python -m uvicorn"))
    assert 0 < commands.index("<network update>") < server_index
    assert sandbox.timeout == 5 * 60
    assert not sandbox.killed


def test_preview_waits_for_the_server_to_answer(monkeypatch):
    monkeypatch.setattr("app.execution.preview.time.sleep", lambda s: None)
    sandbox = FakeSandbox()
    sandbox.commands.down_for = 2
    make_preview(sandbox).start(FILES)
    probes = [c for c, _ in sandbox.commands.calls if "urlopen" in c]
    assert len(probes) == 3


def test_failed_install_removes_the_sandbox():
    sandbox = FakeSandbox()
    sandbox.commands.fail_install = True
    with pytest.raises(PreviewError, match="package installation failed"):
        make_preview(sandbox).start(FILES)
    assert sandbox.killed


def test_project_without_an_app_is_refused_before_creating_a_sandbox():
    created = []
    preview = E2BPreview("key", "", sandbox_factory=lambda **kw: created.append(kw))
    with pytest.raises(PreviewError, match="app/main.py"):
        preview.start({"requirements.txt": "fastapi\n"})
    with pytest.raises(ValueError):
        preview.start({**FILES, "../evil.py": "x"})
    assert created == []


def test_install_list_keeps_only_runtime_packages():
    assert install_list("fastapi>=0.1\nsqlalchemy\npytest\nhttpx\n") == [
        "fastapi", "sqlalchemy", "uvicorn",
    ]  # fmt: skip
