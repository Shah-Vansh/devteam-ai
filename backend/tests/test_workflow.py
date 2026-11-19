"""The LangGraph workflow: routing, limits, pauses, resume and every terminal state.

Agents use a scripted fake LLM, the executor is scripted, and files go through a real
in-process Filesystem MCP server. Checkpoints use memory, except the resume test, which
uses SQLite and a second graph instance, like a second process would.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from app.agents.developer import Developer
from app.agents.planner import Planner
from app.agents.reviewer import Reviewer
from app.agents.tester import Tester
from app.execution.base import ExecutionResult, TestCaseResult
from app.execution.static_only import StaticOnlyExecutor
from app.gitops.approval import new_secret
from app.llm.base import LLMRequestError
from app.llm.fake import FakeLLMClient
from app.mcp_clients.filesystem import FilesystemClient
from app.mcp_clients.git import GitClient
from app.mcp_servers.filesystem.server import build_server
from app.mcp_servers.git.server import build_git_server
from app.workflow.graph import advance, build_graph, current
from app.workflow.state import WorkflowDeps
from tests.conftest import code_changes, finding, review_output

pytestmark = pytest.mark.anyio
RUN = "run-1"
TEST_FILE = "tests/test_todos.py"
TESTS = {"tests/__init__.py": "", TEST_FILE: "def test_create():\n    assert True\n"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@dataclass
class Servers:
    fs: object
    git: object
    secret: str


@pytest.fixture
def server(tmp_path):
    """In-process Filesystem and Git servers sharing one workspaces folder."""
    root = tmp_path / "workspaces"
    secret = new_secret()
    return Servers(build_server(root), build_git_server(root, commit_secret=secret), secret)


@asynccontextmanager
async def clients(servers: Servers):
    async with (
        FilesystemClient(servers.fs) as fs,
        GitClient(servers.git, secret=servers.secret) as git,
    ):
        yield fs, git


class ScriptedExecutor:
    name = "fake"

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def run_tests(self, files, spec):
        self.calls += 1
        return self.results.pop(0)


def passed():
    return ExecutionResult(status="PASSED", executor="fake", passed=3)


def failed():
    case = TestCaseResult(name=f"{TEST_FILE}::test_create", outcome="failed", message="200 != 201")
    return ExecutionResult(status="FAILED", executor="fake", passed=2, failed=1, cases=[case])


def triage(cause, file):
    item = {
        "test": f"{TEST_FILE}::test_create",
        "cause": cause,
        "file": file,
        "reason": "create returns 200",
        "suggested_fix": "return 201",
    }
    return {"items": [item], "summary": "one problem"}


def suite(files=None):
    return code_changes(files or TESTS)


class Harness:
    """One run: a graph with a checkpointer, the deps, and the scripted fakes."""

    def __init__(self, fs, git, responses, executor, saver=None, **options):
        # Most tests are about earlier steps; commit tests switch this off to see the pause.
        options.setdefault("auto_approve_commit", True)
        self.llm = FakeLLMClient(list(responses))
        self.executor = executor
        self.app = build_graph().compile(checkpointer=saver or InMemorySaver())
        self.messages = []
        self.deps = WorkflowDeps(
            planner=Planner(self.llm),
            developer=Developer(self.llm),
            reviewer=Reviewer(self.llm),
            tester=Tester(self.llm),
            executor=executor,
            fs=fs,
            git=git,
            progress=self.messages.append,
            **options,
        )

    async def start(self, **state):
        return await advance(self.app, RUN, self.deps, state)

    async def resume(self, reply):
        return await advance(self.app, RUN, self.deps, Command(resume=reply))


def start_ok(todo_files):
    """Developer writes the todo app; the first review passes; the Tester writes tests."""
    return [code_changes(todo_files), review_output(), suite()]


# ---------- the main path and the execution pause ----------


async def test_pauses_for_approval_then_passes(server, todo_plan_data, todo_files):
    async with clients(server) as (fs, git):
        h = Harness(fs, git, start_ok(todo_files), ScriptedExecutor([passed()]))
        step = await h.start(plan=todo_plan_data)
        assert step.pause == {
            "kind": "execute",
            "executor": "fake",
            "workspace": step.state["workspace"],
        }
        assert h.executor.calls == 0  # nothing ran before approval

        step = await h.resume({"approved": True})
    assert step.finished
    assert step.state["status"] == "SUCCESS"
    assert step.state["llm_calls"] == 3
    assert [r["verdict"] for r in step.state["reports"]] == ["pass"]
    assert step.state["test_rounds"][0]["result"]["status"] == "PASSED"


async def test_auto_approval_does_not_pause(server, todo_plan_data, todo_files):
    async with clients(server) as (fs, git):
        h = Harness(
            fs, git, start_ok(todo_files), ScriptedExecutor([passed()]), auto_approve_execution=True
        )
        step = await h.start(plan=todo_plan_data)
    assert step.pause is None and step.state["status"] == "SUCCESS"


async def test_rejected_execution_is_not_executed(server, todo_plan_data, todo_files):
    async with clients(server) as (fs, git):
        h = Harness(fs, git, start_ok(todo_files), ScriptedExecutor([]))
        await h.start(plan=todo_plan_data)
        step = await h.resume({"approved": False})
    assert step.state["status"] == "NOT_EXECUTED"
    assert h.executor.calls == 0


async def test_cancel_at_approval(server, todo_plan_data, todo_files):
    async with clients(server) as (fs, git):
        h = Harness(fs, git, start_ok(todo_files), ScriptedExecutor([]))
        await h.start(plan=todo_plan_data)
        step = await h.resume({"action": "cancel"})
    assert step.state["status"] == "CANCELLED"


async def test_static_only_executor_skips_the_pause(server, todo_plan_data, todo_files):
    async with clients(server) as (fs, git):
        h = Harness(fs, git, start_ok(todo_files), StaticOnlyExecutor())
        step = await h.start(plan=todo_plan_data)
    assert step.pause is None
    assert step.state["status"] == "NOT_EXECUTED"
    assert step.state["test_rounds"][0]["result"]["passed"] == 0


# ---------- clarification pause ----------


def plan_with_questions(todo_plan_data):
    return todo_plan_data | {"open_questions": ["Should titles be unique?"]}


async def test_clarification_answers_lead_to_a_new_plan(server, todo_plan_data, todo_files):
    responses = [plan_with_questions(todo_plan_data), todo_plan_data, *start_ok(todo_files)]
    async with clients(server) as (fs, git):
        h = Harness(fs, git, responses, ScriptedExecutor([passed()]), auto_approve_execution=True)
        step = await h.start(requirement="Build a todo API")
        assert step.pause == {"kind": "clarify", "questions": ["Should titles be unique?"]}

        step = await h.resume({"answers": ["Yes, reject duplicates"]})
    assert step.state["status"] == "SUCCESS"
    replan = h.llm.requests[1]
    assert replan.agent == "planner"
    assert "Q: Should titles be unique?\nA: Yes, reject duplicates" in replan.user


async def test_empty_answers_keep_the_plan(server, todo_plan_data, todo_files):
    responses = [plan_with_questions(todo_plan_data), *start_ok(todo_files)]
    async with clients(server) as (fs, git):
        h = Harness(fs, git, responses, ScriptedExecutor([passed()]), auto_approve_execution=True)
        await h.start(requirement="Build a todo API")
        step = await h.resume({"answers": [""]})
    assert step.state["status"] == "SUCCESS"
    assert sum(r.agent == "planner" for r in h.llm.requests) == 1


async def test_questions_are_skipped_when_not_asking(server, todo_plan_data, todo_files):
    responses = [plan_with_questions(todo_plan_data), *start_ok(todo_files)]
    async with clients(server) as (fs, git):
        h = Harness(
            fs,
            git,
            responses,
            ScriptedExecutor([passed()]),
            ask_clarifications=False,
            auto_approve_execution=True,
        )
        step = await h.start(requirement="Build a todo API")
    assert step.pause is None and step.state["status"] == "SUCCESS"


async def test_cancel_at_clarification(server, todo_plan_data):
    async with clients(server) as (fs, git):
        h = Harness(fs, git, [plan_with_questions(todo_plan_data)], ScriptedExecutor([]))
        await h.start(requirement="Build a todo API")
        step = await h.resume({"action": "cancel"})
    assert step.state["status"] == "CANCELLED"


# ---------- review loop ----------


async def test_review_limit_ends_as_failed_review(server, todo_plan_data, todo_files):
    bad = review_output(finding(message="still wrong"))
    responses = [code_changes(todo_files), bad]
    for i in range(2):
        responses += [code_changes({"app/main.py": todo_files["app/main.py"] + f"# {i}\n"}), bad]
    async with clients(server) as (fs, git):
        h = Harness(fs, git, responses, ScriptedExecutor([]))
        step = await h.start(plan=todo_plan_data)
    assert step.state["status"] == "FAILED_REVIEW"
    assert len(step.state["reports"]) == 3
    assert step.state["review_rounds"] == 2
    assert h.executor.calls == 0


async def test_unusable_revision_ends_as_failed_review(server, todo_plan_data, todo_files):
    empty = {"files": [], "notes": ""}
    responses = [code_changes(todo_files), review_output(finding()), empty, empty]
    async with clients(server) as (fs, git):
        h = Harness(fs, git, responses, ScriptedExecutor([]))
        step = await h.start(plan=todo_plan_data)
    assert step.state["status"] == "FAILED_REVIEW"
    assert "no usable answer" in step.state["stop_reason"]


# ---------- test and fix loop ----------


async def test_code_fix_is_reviewed_again_before_retesting(server, todo_plan_data, todo_files):
    fixed = {"app/main.py": todo_files["app/main.py"].replace('"Todo API"', '"Todo"')}
    responses = [
        *start_ok(todo_files),
        triage("bad_code", "app/main.py"),
        code_changes(fixed),
        review_output(),  # the fix is reviewed
    ]
    async with clients(server) as (fs, git):
        h = Harness(
            fs, git, responses, ScriptedExecutor([failed(), passed()]), auto_approve_execution=True
        )
        step = await h.start(plan=todo_plan_data)
    assert step.state["status"] == "SUCCESS"
    assert [r.agent for r in h.llm.requests] == [
        "developer", "reviewer", "tester", "tester", "developer", "reviewer",
    ]  # fmt: skip
    assert step.state["fix_rounds"] == 1
    assert len(step.state["reports"]) == 2
    assert step.state["test_rounds"][0]["triage"]["items"][0]["cause"] == "bad_code"


async def test_test_fix_goes_straight_back_to_running(server, todo_plan_data, todo_files):
    new_test = {TEST_FILE: "def test_create():\n    assert 1 == 1\n"}
    responses = [*start_ok(todo_files), triage("bad_test", TEST_FILE), suite(new_test)]
    async with clients(server) as (fs, git):
        h = Harness(
            fs, git, responses, ScriptedExecutor([failed(), passed()]), auto_approve_execution=True
        )
        step = await h.start(plan=todo_plan_data)
        content = await fs.read_file(step.state["workspace"], TEST_FILE)
    assert step.state["status"] == "SUCCESS"
    assert len(step.state["reports"]) == 1  # no extra review for test-only changes
    assert content == new_test[TEST_FILE]


async def test_environment_failure_ends_as_failed_tests(server, todo_plan_data, todo_files):
    responses = [*start_ok(todo_files), triage("environment", "")]
    async with clients(server) as (fs, git):
        h = Harness(fs, git, responses, ScriptedExecutor([failed()]), auto_approve_execution=True)
        step = await h.start(plan=todo_plan_data)
    assert step.state["status"] == "FAILED_TESTS"
    assert "environment problem" in step.state["stop_reason"]


async def test_fix_round_limit_ends_as_failed_tests(server, todo_plan_data, todo_files):
    responses = [*start_ok(todo_files)]
    for i in range(2):
        responses += [triage("bad_test", TEST_FILE), suite({TEST_FILE: f"# try {i}\n"})]
    async with clients(server) as (fs, git):
        h = Harness(
            fs, git, responses, ScriptedExecutor([failed()] * 3), auto_approve_execution=True
        )
        step = await h.start(plan=todo_plan_data)
    assert step.state["status"] == "FAILED_TESTS"
    assert step.state["fix_rounds"] == 2
    assert h.executor.calls == 3


async def test_disallowed_package_is_fixed_and_reviewed(server, todo_plan_data, todo_files):
    todo_files["requirements.txt"] = "fastapi\nrequests\n"
    responses = [
        code_changes(todo_files),
        review_output(),
        suite(),
        code_changes({"requirements.txt": "fastapi\n"}),
        review_output(),
    ]
    async with clients(server) as (fs, git):
        h = Harness(fs, git, responses, ScriptedExecutor([passed()]), auto_approve_execution=True)
        step = await h.start(plan=todo_plan_data)
    assert step.state["status"] == "SUCCESS"
    assert "packages not available in the sandbox: requests" in h.llm.requests[3].user


# ---------- errors and limits ----------


async def test_provider_outage_is_an_error_state_not_an_exception(server, todo_plan_data):
    async with clients(server) as (fs, git):
        h = Harness(fs, git, [LLMRequestError("429 tokens per day")], ScriptedExecutor([]))
        step = await h.start(plan=todo_plan_data)
    assert step.finished and step.state["status"] == "ERROR"
    assert "tokens per day" in step.state["stop_reason"]


async def test_llm_budget_is_enforced_across_stages(server, todo_plan_data, todo_files):
    async with clients(server) as (fs, git):
        h = Harness(fs, git, start_ok(todo_files), ScriptedExecutor([]), max_llm_calls=2)
        step = await h.start(plan=todo_plan_data)
    assert step.state["status"] == "ERROR"
    assert "limit is 2" in step.state["stop_reason"]


# ---------- resume from SQLite in a new graph instance ----------


async def test_paused_run_resumes_from_sqlite_in_a_new_instance(
    server, tmp_path, todo_plan_data, todo_files
):
    db = str(tmp_path / "checkpoints.db")
    async with clients(server) as (fs, git):
        async with AsyncSqliteSaver.from_conn_string(db) as saver:
            first = Harness(fs, git, start_ok(todo_files), ScriptedExecutor([]), saver=saver)
            step = await first.start(plan=todo_plan_data)
            assert step.pause["kind"] == "execute"

        # Later, a different process: new saver, new graph, new deps, same run id.
        async with AsyncSqliteSaver.from_conn_string(db) as saver:
            second = Harness(fs, git, [], ScriptedExecutor([passed()]), saver=saver)
            saved = await current(second.app, RUN)
            assert saved.pause["kind"] == "execute"
            assert saved.state["llm_calls"] == 3
            step = await second.resume({"approved": True})
    assert step.state["status"] == "SUCCESS"
    assert second.llm.requests == []  # nothing was redone


async def test_unknown_run_has_no_state(server):
    async with clients(server) as (fs, git):
        h = Harness(fs, git, [], ScriptedExecutor([]))
        assert await current(h.app, "missing") is None


# ---------- ported from the Phase 4 loop tests ----------


async def test_passes_after_one_revision(server, todo_plan_data, todo_files):
    fixed = {"app/main.py": todo_files["app/main.py"].replace('"Todo API"', '"Todo API v2"')}
    responses = [
        code_changes(todo_files),
        review_output(finding(message="create returns 200")),
        code_changes(fixed),
        review_output(),
        suite(),
    ]
    async with clients(server) as (fs, git):
        h = Harness(fs, git, responses, ScriptedExecutor([passed()]), auto_approve_execution=True)
        step = await h.start(plan=todo_plan_data)
        main = await fs.read_file(step.state["workspace"], "app/main.py")
    assert step.state["status"] == "SUCCESS"
    assert [r["verdict"] for r in step.state["reports"]] == ["changes_needed", "pass"]
    assert step.state["review_rounds"] == 1
    assert main == fixed["app/main.py"]
    assert "create returns 200" in h.llm.requests[2].user  # findings reached the Developer


async def test_sandbox_error_is_an_error_state(server, todo_plan_data, todo_files):
    error = ExecutionResult(status="ERROR", executor="fake", detail="package installation failed")
    async with clients(server) as (fs, git):
        h = Harness(
            fs, git, start_ok(todo_files), ScriptedExecutor([error]), auto_approve_execution=True
        )
        step = await h.start(plan=todo_plan_data)
    assert step.state["status"] == "ERROR"
    assert "package installation failed" in step.state["stop_reason"]


async def test_unusable_fix_ends_as_failed_tests_and_keeps_rounds(
    server, todo_plan_data, todo_files
):
    from app.llm.base import LLMResponseError

    responses = [
        *start_ok(todo_files),
        triage("bad_test", TEST_FILE),
        LLMResponseError("tester: no valid TestSuite after 2 attempts"),
    ]
    async with clients(server) as (fs, git):
        h = Harness(fs, git, responses, ScriptedExecutor([failed()]), auto_approve_execution=True)
        step = await h.start(plan=todo_plan_data)
    assert step.state["status"] == "FAILED_TESTS"
    assert "no usable answer" in step.state["stop_reason"]
    assert step.state["test_rounds"][0]["triage"] is not None


def test_workspace_names_are_unique_and_valid():
    from app.workflow.workspace_io import new_workspace_name
    from app.workspace.paths import validate_workspace_name

    names = {new_workspace_name("todo-api") for _ in range(20)}
    assert len(names) == 20
    long = new_workspace_name("x" * 80)
    assert validate_workspace_name(long) == long


# ---------- commit approval and the Git server (Phase 6) ----------


async def run_to_commit_pause(h, todo_plan_data):
    step = await h.start(plan=todo_plan_data)
    assert step.pause["kind"] == "commit"
    return step


async def test_commit_pause_then_success_records_history(server, todo_plan_data, todo_files):
    async with clients(server) as (fs, git):
        h = Harness(
            fs,
            git,
            start_ok(todo_files),
            ScriptedExecutor([passed()]),
            auto_approve_execution=True,
            auto_approve_commit=False,
        )
        step = await run_to_commit_pause(h, todo_plan_data)
        ws = step.state["workspace"]
        assert TEST_FILE in step.pause["files"] and "app/main.py" in step.pause["files"]
        assert step.pause["message"].startswith("Add todo-api")
        assert "Tests: 3 passed (fake)" in step.pause["message"]

        step = await h.resume({"approved": True})
        history = await git.get_commit_history(ws)
        status = await git.get_git_status(ws)
    assert step.state["status"] == "SUCCESS"
    assert step.state["commit"]["commit"] == history[0]["commit"]
    assert history[0]["subject"] == "Add todo-api"
    assert history[0]["author"] == "DevTeam AI"
    assert status["clean"] is True
    assert TEST_FILE in step.state["commit"]["files"]


async def test_edited_commit_message_is_used(server, todo_plan_data, todo_files):
    async with clients(server) as (fs, git):
        h = Harness(
            fs, git, start_ok(todo_files), ScriptedExecutor([passed()]),
            auto_approve_execution=True, auto_approve_commit=False,
        )  # fmt: skip
        step = await run_to_commit_pause(h, todo_plan_data)
        step = await h.resume({"approved": True, "message": "First version of the todo API"})
        history = await git.get_commit_history(step.state["workspace"])
    assert history[0]["subject"] == "First version of the todo API"


async def test_declined_commit_is_not_committed(server, todo_plan_data, todo_files):
    from app.mcp_clients.git import GitToolError

    async with clients(server) as (fs, git):
        h = Harness(
            fs, git, start_ok(todo_files), ScriptedExecutor([passed()]),
            auto_approve_execution=True, auto_approve_commit=False,
        )  # fmt: skip
        step = await run_to_commit_pause(h, todo_plan_data)
        step = await h.resume({"approved": False})
        with pytest.raises(GitToolError) as info:
            await git.get_commit_history(step.state["workspace"])
    assert step.state["status"] == "NOT_COMMITTED"
    assert info.value.code == "NOT_A_REPOSITORY"  # nothing was even initialised


async def test_cancel_at_commit(server, todo_plan_data, todo_files):
    async with clients(server) as (fs, git):
        h = Harness(
            fs, git, start_ok(todo_files), ScriptedExecutor([passed()]),
            auto_approve_execution=True, auto_approve_commit=False,
        )  # fmt: skip
        await run_to_commit_pause(h, todo_plan_data)
        step = await h.resume({"action": "cancel"})
    assert step.state["status"] == "CANCELLED"


async def test_file_changed_during_the_pause_blocks_the_commit(server, todo_plan_data, todo_files):
    """The approval covers what was shown. An edit made while the human was deciding must
    not slip into the commit, even though the paused node runs again on resume."""
    async with clients(server) as (fs, git):
        h = Harness(
            fs, git, start_ok(todo_files), ScriptedExecutor([passed()]),
            auto_approve_execution=True, auto_approve_commit=False,
        )  # fmt: skip
        step = await run_to_commit_pause(h, todo_plan_data)
        ws = step.state["workspace"]
        await fs.update_file(ws, "app/main.py", "import os  # sneaked in after approval\n")

        step = await h.resume({"approved": True})
        history = await git.get_commit_history(ws)
    assert step.state["status"] == "NOT_COMMITTED"
    assert "CONTENT_CHANGED" in step.state["stop_reason"]
    assert history == []


async def test_commit_resumes_after_restart_with_a_new_secret(
    server, tmp_path, todo_plan_data, todo_files
):
    """A paused commit approved after a restart: the new Git server has a new secret, and
    the token is issued after approval by the new client, so the commit still works."""
    db = str(tmp_path / "checkpoints.db")
    async with clients(server) as (fs, git):
        async with AsyncSqliteSaver.from_conn_string(db) as saver:
            first = Harness(
                fs, git, start_ok(todo_files), ScriptedExecutor([passed()]), saver=saver,
                auto_approve_execution=True, auto_approve_commit=False,
            )  # fmt: skip
            await run_to_commit_pause(first, todo_plan_data)

    secret = new_secret()  # a restarted Git server never reuses the old secret
    restarted = Servers(
        server.fs, build_git_server(tmp_path / "workspaces", commit_secret=secret), secret
    )
    async with clients(restarted) as (fs, git):
        async with AsyncSqliteSaver.from_conn_string(db) as saver:
            second = Harness(fs, git, [], ScriptedExecutor([]), saver=saver)
            step = await second.resume({"approved": True})
    assert step.state["status"] == "SUCCESS"
