"""The Tester agent (tests, triage, test fixes) with a fake LLM, and test-name handling.
The test-and-fix loop itself is tested in test_workflow.py."""

import pytest
from pydantic import ValidationError

from app.agents.common import AgentOutputError
from app.agents.tester import FAILURES_BUDGET, Tester, failures_block, relevant_test_files
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


MANY_TESTS = {
    "tests/__init__.py": "",
    "tests/conftest.py": "# shared fixtures\n",
    TEST_FILE: "def test_create():\n    assert True\n",
    "tests/test_list.py": "def test_list():\n    assert True\n",
    "tests/test_delete.py": "def test_delete():\n    assert True\n",
}


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        ([f"{TEST_FILE}::test_create"], {TEST_FILE}),
        (["tests.test_list.test_list"], {"tests/test_list.py"}),
        (["tests/test_delete.py"], {"tests/test_delete.py"}),
        (
            [f"{TEST_FILE}::test_create", "tests/test_list.py::test_list"],
            {TEST_FILE, "tests/test_list.py"},
        ),
    ],
)
def test_relevant_test_files_keeps_failing_modules_and_fixtures(names, expected):
    picked = relevant_test_files(MANY_TESTS, names)
    assert set(picked) == expected | {"tests/__init__.py", "tests/conftest.py"}


def test_relevant_test_files_keeps_everything_when_nothing_matches():
    assert relevant_test_files(MANY_TESTS, ["test_create"]) == MANY_TESTS


def test_triage_and_fixes_show_only_the_relevant_test_files(todo_plan, todo_files):
    # Found live: every test file in the prompt made one request larger than the free
    # tier's 8,000 tokens per minute.
    fixed = suite({TEST_FILE: "def test_create():\n    assert 1\n"})
    llm = FakeLLMClient([triage(), fixed])
    tester = Tester(llm)
    call = tester.triage(todo_plan, todo_files, MANY_TESTS, failed())
    item = call.data.items[0].model_copy(update={"cause": "bad_test", "file": TEST_FILE})
    tester.fix_tests(todo_plan, todo_files, MANY_TESTS, [item])
    for request in llm.requests:
        assert TEST_FILE in request.user and "tests/conftest.py" in request.user
        assert "tests/test_list.py" not in request.user
        assert "tests/test_delete.py" not in request.user


def test_triage_may_still_blame_a_test_file_it_was_not_shown(todo_plan, todo_files):
    other = triage(cause="bad_test", file="tests/test_list.py")
    call = Tester(FakeLLMClient([other])).triage(todo_plan, todo_files, MANY_TESTS, failed())
    assert call.data.items[0].file == "tests/test_list.py"


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
        # Found in the benchmark (b04): a model naming only the test function.
        ("test_redirect_success", "tests/test_redirect.py::test_redirect_success", True),
        ("test_x", "tests/test_a.py::test_y", False),
        ("test_a", "tests/test_a.py::test_x", False),  # a bare module is not a test name
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


# ---------- failure messages within a budget ----------


def many_failures(messages):
    cases = [
        TestCaseResult(name=f"{TEST_FILE}::test_{i}", outcome="failed", message=m)
        for i, m in enumerate(messages)
    ]
    return ExecutionResult(status="FAILED", executor="fake", failed=len(cases), cases=cases)


def test_identical_errors_are_shown_once():
    same = "x" * 2000 + "\nE   ModuleNotFoundError: No module named 'app.db'"
    block = failures_block(many_failures([same.replace("x", str(i % 10)) for i in range(8)]))
    assert block.count("ModuleNotFoundError") == 1
    assert block.count("(same error as tests/test_todos.py::test_0)") == 7


def test_failure_messages_keep_their_end_and_fit_the_budget():
    messages = [("traceback line\n" * 200) + f"E   assert {i} == 201" for i in range(8)]
    block = failures_block(many_failures(messages))
    assert all(f"E   assert {i} == 201" in block for i in range(8))
    assert len(block) < FAILURES_BUDGET + 8 * 80
