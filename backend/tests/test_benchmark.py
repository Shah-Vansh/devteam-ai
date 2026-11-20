"""The end-to-end benchmark runner, with the same fakes as the workflow tests."""

import pytest

from app.evaluation.benchmark import CaseResult, aggregate, markdown_table, run_case
from tests.conftest import code_changes, finding, review_output
from tests.test_workflow import TESTS, Harness, ScriptedExecutor, clients, passed

CASE = {"id": "b02", "difficulty": "easy", "requirement": "Build a todo API"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def server(tmp_path):
    from app.gitops.approval import new_secret
    from app.mcp_servers.filesystem.server import build_server
    from app.mcp_servers.git.server import build_git_server
    from tests.test_workflow import Servers

    root = tmp_path / "workspaces"
    secret = new_secret()
    return Servers(build_server(root), build_git_server(root, commit_secret=secret), secret)


@pytest.mark.anyio
async def test_a_case_runs_to_success_answering_every_pause(server, todo_plan_data, todo_files):
    questions = todo_plan_data | {"open_questions": ["Unique titles?"]}
    responses = [questions, code_changes(todo_files), review_output(), code_changes(TESTS)]
    async with clients(server) as (fs, git):
        # Pauses are left on (no auto approval in deps): the runner must answer them.
        h = Harness(fs, git, responses, ScriptedExecutor([passed()]), auto_approve_commit=False)
        result = await run_case(h.app, h.deps, "run-1", CASE, "fake-model")
    assert result.status == "SUCCESS"
    assert result.committed and result.tests_passed == 3 and result.tests_total == 3
    assert result.llm_calls == 4 and result.reviews == 1
    assert result.seconds >= 0


@pytest.mark.anyio
async def test_a_failing_case_is_recorded_as_it_ended(server, todo_plan_data, todo_files):
    bad = review_output(finding(message="still wrong"))
    responses = [todo_plan_data, code_changes(todo_files), bad]
    for i in range(2):
        responses += [code_changes({"app/main.py": todo_files["app/main.py"] + f"# {i}\n"}), bad]
    async with clients(server) as (fs, git):
        h = Harness(fs, git, responses, ScriptedExecutor([]))
        result = await run_case(h.app, h.deps, "run-2", CASE, "fake-model")
    assert result.status == "FAILED_REVIEW"
    assert result.review_rounds == 2 and result.test_runs == 0
    assert "high-severity" in result.stop_reason


def result(case_id, difficulty, status, passed=0, total=0):
    return CaseResult(
        id=case_id, difficulty=difficulty, run_id="r", status=status, stop_reason="",
        review_rounds=0, fix_rounds=0, reviews=1, test_runs=1, tests_passed=passed,
        tests_total=total, committed=status == "SUCCESS", llm_calls=4, input_tokens=100,
        output_tokens=50, seconds=10.0,
    )  # fmt: skip


def test_aggregate_counts_success_per_difficulty():
    results = [
        result("b01", "easy", "SUCCESS", 5, 5),
        result("b02", "easy", "FAILED_TESTS", 3, 5),
        result("b07", "hard", "SUCCESS", 8, 8),
    ]
    summary = aggregate(results)
    assert summary["success"] == 2 and summary["cases"] == 3
    assert summary["by_difficulty"] == {
        "easy": {"cases": 2, "success": 1},
        "hard": {"cases": 1, "success": 1},
    }
    assert summary["by_status"] == {"SUCCESS": 2, "FAILED_TESTS": 1}
    assert (summary["tests_passed"], summary["tests_total"]) == (16, 18)
    assert summary["tokens"] == 450


def test_markdown_table_has_one_row_per_case():
    table = markdown_table([result("b01", "easy", "SUCCESS", 5, 5)])
    assert table.splitlines()[2] == "| b01 | easy | SUCCESS | 0 | 0 | 5/5 | 4 | 150 | 10 s |"


def test_account_ids_are_removed_from_stop_reasons():
    from app.evaluation.benchmark import redact

    reason = "Rate limit reached for model x in organization `org_01abcXYZ` service tier"
    assert (
        redact(reason)
        == "Rate limit reached for model x in organization `org_<redacted>` service tier"
    )
