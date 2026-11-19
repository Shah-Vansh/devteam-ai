"""The Tester agent (tests, triage, test fixes) with a fake LLM, and test-name handling.
The test-and-fix loop itself is tested in test_workflow.py."""

import pytest
from pydantic import ValidationError

from app.agents.common import AgentOutputError
from app.agents.tester import Tester
from app.execution.base import ExecutionResult, TestCaseResult
from app.llm.fake import FakeLLMClient
from app.schemas.testing import TestSuite
from tests.conftest import code_changes

WS = "todo-api-abc123"
TEST_FILE = "tests/test_todos.py"
TESTS = {
    "tests/__init__.py": "",
    TEST_FILE: "def test_create():\n    assert True\n",
}


def suite(files=None):
    return code_changes(files or TESTS)


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
