"""Tester agent and the full build-and-test run, with a fake LLM, a scripted executor and
a real in-process Filesystem MCP server."""

import pytest
from pydantic import ValidationError

from app.agents.common import AgentOutputError
from app.agents.developer import Developer
from app.agents.reviewer import Reviewer
from app.agents.tester import Tester
from app.execution.base import ExecutionResult, TestCaseResult
from app.execution.static_only import StaticOnlyExecutor
from app.llm.fake import FakeLLMClient
from app.mcp_clients.filesystem import FilesystemClient
from app.mcp_servers.filesystem.server import build_server
from app.pipeline.budget import LLMBudget, LLMBudgetExceeded
from app.pipeline.run import build_and_test
from app.schemas.testing import TestSuite
from tests.conftest import code_changes, finding, review_output

WS = "todo-api-abc123"
TEST_FILE = "tests/test_todos.py"
TESTS = {
    "tests/__init__.py": "",
    TEST_FILE: "def test_create():\n    assert True\n",
}


def suite(files=None):
    return code_changes(files or TESTS)


def passed(n=3):
    return ExecutionResult(status="PASSED", executor="fake", passed=n)


def failed(name=f"{TEST_FILE}::test_create", message="assert 200 == 201"):
    case = TestCaseResult(name=name, outcome="failed", message=message)
    return ExecutionResult(status="FAILED", executor="fake", passed=2, failed=1, cases=[case])


def triage(cause="bad_code", file="app/main.py", test=f"{TEST_FILE}::test_create"):
    item = {
        "test": test,
        "cause": cause,
        "file": file,
        "reason": "create returns 200",
        "suggested_fix": "return 201",
    }
    return {"items": [item], "summary": "one problem"}


class ScriptedExecutor:
    name = "fake"

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def run_tests(self, files, spec):
        self.calls.append((dict(files), spec))
        return self.results.pop(0)


# ---------- TestSuite schema and Tester agent ----------


@pytest.mark.parametrize(
    "path", ["app/main.py", "tests/helpers.py", "tests/sub/test_x.py", "test_x.py"]
)
def test_suite_only_accepts_test_files(path):
    with pytest.raises(ValidationError):
        TestSuite.model_validate(code_changes({path: "x = 1\n"}))


def test_write_tests_requires_a_test_module(todo_plan, todo_files):
    llm = FakeLLMClient([suite({"tests/conftest.py": "x = 1\n"}), suite()])
    call = Tester(llm).write_tests(todo_plan, todo_files)
    assert set(call.data.as_dict()) == set(TESTS)
    assert "no test_*.py file" in llm.requests[1].user
    assert "<plan>" in llm.requests[0].user and "app/store.py" in llm.requests[0].user


def test_triage_must_classify_every_failure_with_a_valid_file(todo_plan, todo_files):
    wrong_file = triage(cause="bad_code", file=TEST_FILE)  # bad_code must name an app file
    llm = FakeLLMClient([wrong_file, triage()])
    call = Tester(llm).triage(todo_plan, todo_files, TESTS, failed())
    assert call.data.items[0].file == "app/main.py"
    retry = llm.requests[1].user
    assert "bad_code must name an app file" in retry
    assert "assert 200 == 201" in llm.requests[0].user  # the failure message is shown


def test_triage_missing_a_failure_is_rejected(todo_plan, todo_files):
    other = triage(test="tests/test_todos.py::test_other")
    llm = FakeLLMClient([other, other])
    with pytest.raises(AgentOutputError, match="not classified"):
        Tester(llm).triage(todo_plan, todo_files, TESTS, failed())


# ---------- build_and_test ----------


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def server(tmp_path):
    return build_server(tmp_path / "workspaces")


async def run(server, plan, responses, executor, *, approve=True, max_calls=40, **kw):
    llm = FakeLLMClient(responses)
    budget = LLMBudget(max_calls)
    rounds = []

    async def approval():
        return approve

    async with FilesystemClient(server) as fs:
        result = await build_and_test(
            plan,
            workspace=WS,
            developer=Developer(llm),
            reviewer=Reviewer(llm),
            tester=Tester(llm),
            executor=executor,
            fs=fs,
            budget=budget,
            approve_execution=approval,
            on_test_round=rounds.append,
            **kw,
        )
        files = {p: await fs.read_file(WS, p) for p in await fs.list_files(WS)}
    return result, llm, budget, rounds, files


def start(todo_files):
    """Developer writes the todo app; the review passes."""
    return [code_changes(todo_files), review_output()]


@pytest.mark.anyio
async def test_passing_tests_end_the_run(server, todo_plan, todo_files):
    executor = ScriptedExecutor([passed()])
    result, _, budget, rounds, files = await run(
        server, todo_plan, [*start(todo_files), suite()], executor
    )
    assert result.status == "TESTS_PASSED"
    assert result.develop.status == "REVIEW_PASSED"
    assert budget.calls == 3
    sent_files, spec = executor.calls[0]
    assert TEST_FILE in sent_files and "app/main.py" in sent_files
    assert spec.packages == ["fastapi", "uvicorn", "pytest", "httpx"]
    assert TEST_FILE in files  # tests are part of the workspace
    assert [r.round for r in rounds] == [1]


@pytest.mark.anyio
async def test_bad_code_goes_to_the_developer_then_passes(server, todo_plan, todo_files):
    fixed = {"app/main.py": todo_files["app/main.py"].replace('"Todo API"', '"Todo"')}
    responses = [*start(todo_files), suite(), triage("bad_code"), code_changes(fixed)]
    executor = ScriptedExecutor([failed(), passed()])
    result, llm, _, rounds, files = await run(server, todo_plan, responses, executor)

    assert result.status == "TESTS_PASSED"
    assert result.fix_rounds == 1
    assert files["app/main.py"] == fixed["app/main.py"]
    assert rounds[0].triage.items[0].cause == "bad_code"
    assert "create returns 200" in llm.requests[-1].user  # triage reached the Developer


@pytest.mark.anyio
async def test_bad_test_goes_to_the_tester(server, todo_plan, todo_files):
    new_test = {TEST_FILE: "def test_create():\n    assert 1 == 1\n"}
    responses = [*start(todo_files), suite(), triage("bad_test", file=TEST_FILE), suite(new_test)]
    executor = ScriptedExecutor([failed(), passed()])
    result, _, _, _, files = await run(server, todo_plan, responses, executor)
    assert result.status == "TESTS_PASSED"
    assert files[TEST_FILE] == new_test[TEST_FILE]
    assert files["app/main.py"] == todo_files["app/main.py"]  # app untouched


@pytest.mark.anyio
async def test_environment_failure_stops_without_fixes(server, todo_plan, todo_files):
    responses = [*start(todo_files), suite(), triage("environment", file="")]
    executor = ScriptedExecutor([failed()])
    result, _, _, _, _ = await run(server, todo_plan, responses, executor)
    assert result.status == "FAILED_TESTS"
    assert "environment problem" in result.stop_reason
    assert result.fix_rounds == 0


@pytest.mark.anyio
async def test_fix_rounds_are_limited(server, todo_plan, todo_files):
    responses = [*start(todo_files), suite()]
    for i in range(2):
        responses += [triage("bad_test", file=TEST_FILE), suite({TEST_FILE: f"# try {i}\n"})]
    executor = ScriptedExecutor([failed(), failed(), failed()])
    result, llm, _, _, _ = await run(server, todo_plan, responses, executor, max_fix_rounds=2)
    assert result.status == "FAILED_TESTS"
    assert result.fix_rounds == 2
    assert len(executor.calls) == 3
    assert llm.responses == []


@pytest.mark.anyio
async def test_no_approval_means_nothing_runs(server, todo_plan, todo_files):
    executor = ScriptedExecutor([])
    result, _, _, _, _ = await run(
        server, todo_plan, [*start(todo_files), suite()], executor, approve=False
    )
    assert result.status == "NOT_EXECUTED"
    assert executor.calls == []


@pytest.mark.anyio
async def test_static_only_executor_reports_not_executed(server, todo_plan, todo_files):
    result, _, _, _, _ = await run(
        server, todo_plan, [*start(todo_files), suite()], StaticOnlyExecutor()
    )
    assert result.status == "NOT_EXECUTED"
    assert result.last_test_result.passed == 0


@pytest.mark.anyio
async def test_sandbox_error_is_reported_as_error(server, todo_plan, todo_files):
    error = ExecutionResult(status="ERROR", executor="fake", detail="package installation failed")
    result, _, _, _, _ = await run(
        server, todo_plan, [*start(todo_files), suite()], ScriptedExecutor([error])
    )
    assert result.status == "ERROR"
    assert "package installation failed" in result.stop_reason


@pytest.mark.anyio
async def test_disallowed_package_is_sent_back_to_the_developer(server, todo_plan, todo_files):
    todo_files["requirements.txt"] = "fastapi\nrequests\n"
    fixed = {"requirements.txt": "fastapi\n"}
    responses = [code_changes(todo_files), review_output(), suite(), code_changes(fixed)]
    executor = ScriptedExecutor([passed()])
    result, llm, _, _, _ = await run(server, todo_plan, responses, executor)
    assert result.status == "TESTS_PASSED"
    assert result.fix_rounds == 1
    assert "packages not available in the sandbox: requests" in llm.requests[-1].user
    assert executor.calls[0][1].packages == ["fastapi", "pytest", "httpx"]


@pytest.mark.anyio
async def test_failed_review_skips_testing(server, todo_plan, todo_files):
    bad = review_output(finding(message="broken"))
    responses = [
        code_changes(todo_files),
        bad,
        {"files": [], "notes": ""},
        {"files": [], "notes": ""},
    ]
    executor = ScriptedExecutor([])
    result, _, _, _, _ = await run(server, todo_plan, responses, executor)
    assert result.status == "FAILED_REVIEW"
    assert executor.calls == []


@pytest.mark.anyio
async def test_budget_is_shared_across_stages(server, todo_plan, todo_files):
    with pytest.raises(LLMBudgetExceeded):
        await run(
            server, todo_plan, [*start(todo_files), suite()], ScriptedExecutor([]), max_calls=2
        )


@pytest.mark.anyio
async def test_unusable_fix_ends_as_failed_tests_and_keeps_rounds(server, todo_plan, todo_files):
    from app.llm.base import LLMResponseError

    responses = [
        *start(todo_files),
        suite(),
        triage("bad_test", file=TEST_FILE),
        LLMResponseError("tester: no valid TestSuite after 2 attempts"),
    ]
    result, _, _, rounds, _ = await run(server, todo_plan, responses, ScriptedExecutor([failed()]))
    assert result.status == "FAILED_TESTS"
    assert "could not produce a usable answer" in result.stop_reason
    assert len(result.test_rounds) == 1 and rounds[0].triage is not None


@pytest.mark.anyio
async def test_provider_outage_during_testing_is_an_error(server, todo_plan, todo_files):
    from app.llm.base import LLMRequestError

    responses = [*start(todo_files), LLMRequestError("429 tokens per day")]
    result, _, _, _, _ = await run(server, todo_plan, responses, ScriptedExecutor([]))
    assert result.status == "ERROR"
    assert "tokens per day" in result.stop_reason


@pytest.mark.parametrize(
    ("given", "actual", "same"),
    [
        ("tests/test_a.py::test_x", "tests/test_a.py::test_x", True),
        ("tests.test_a.test_x", "tests/test_a.py::test_x", True),
        ("tests/test_a.py", "tests/test_a.py::(collection)", True),
        (r"tests\test_a.py::test_x", "tests/test_a.py::test_x", True),  # Windows-style
        ("tests/test_a.py::test_y", "tests/test_a.py::test_x", False),
        ("tests/test_b.py", "tests/test_a.py::(collection)", False),
        ("", "tests/test_a.py::test_x", False),
    ],
)
def test_same_test_accepts_common_spellings(given, actual, same):
    from app.agents.tester import same_test

    assert same_test(given, actual) is same


def test_collection_errors_get_a_readable_name():
    from app.execution.junit import parse_junit

    xml = (
        '<testsuites><testcase classname="" name="tests.test_create">'
        '<error message="collection failure">NameError: TestClient</error></testcase></testsuites>'
    )
    (case,) = parse_junit(xml)
    assert case.name == "tests/test_create.py::(collection)"
    assert case.outcome == "error" and "NameError" in case.message
