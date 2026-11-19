import pytest

from app.agents.common import AgentOutputError
from app.agents.developer import Developer, DeveloperInputError
from app.llm.fake import FakeLLMClient
from app.schemas.review import Finding
from tests.conftest import code_changes, finding


def test_generate_sends_plan_as_data_and_returns_files(todo_plan, todo_files):
    llm = FakeLLMClient([code_changes(todo_files)])
    call = Developer(llm).generate(todo_plan)

    assert call.data.as_dict() == todo_files
    assert len(call.usages) == 1
    request = llm.requests[0]
    assert request.agent == "developer"
    assert "<plan>" in request.user and "</plan>" in request.user
    assert "open_questions" not in request.user
    assert "Never use `eval`" in request.system


def test_missing_planned_file_triggers_one_corrective_retry(todo_plan, todo_files):
    partial = {k: v for k, v in todo_files.items() if k != "app/store.py"}
    llm = FakeLLMClient([code_changes(partial), code_changes(todo_files)])
    call = Developer(llm).generate(todo_plan)

    assert call.data.as_dict() == todo_files
    assert len(call.usages) == 2
    assert "missing: app/store.py" in llm.requests[1].user


def test_extra_file_twice_is_an_error(todo_plan, todo_files):
    extra = {**todo_files, "app/secret.py": "x = 1\n"}
    llm = FakeLLMClient([code_changes(extra), code_changes(extra)])
    with pytest.raises(AgentOutputError, match="not requested now: app/secret.py"):
        Developer(llm).generate(todo_plan)


def test_revise_sends_files_and_findings(todo_plan, todo_files):
    fixed = {"app/main.py": todo_files["app/main.py"] + "\n# fixed\n"}
    llm = FakeLLMClient([code_changes(fixed)])
    issue = Finding(source="reviewer", **finding(line=12, message="wrong status code"))

    call = Developer(llm).revise(todo_plan, todo_files, [issue])

    assert call.data.as_dict() == fixed
    user = llm.requests[0].user
    assert '<file path="app/main.py">' in user  # file with a finding: full text
    assert '<outline path="app/store.py">' in user  # other files: outline only
    assert '<file path="app/store.py">' not in user
    assert "[high][bug] app/main.py line 12: wrong status code" in user


def test_revise_returning_unchanged_files_is_retried(todo_plan, todo_files):
    same = {"app/main.py": todo_files["app/main.py"]}
    changed = {"app/main.py": todo_files["app/main.py"] + "\n"}
    llm = FakeLLMClient([code_changes(same), code_changes(changed)])
    issue = Finding(source="reviewer", **finding())

    call = Developer(llm).revise(todo_plan, todo_files, [issue])
    assert len(call.usages) == 2
    assert "none of the returned files differ" in llm.requests[1].user


def test_revise_without_findings_makes_no_call(todo_plan, todo_files):
    llm = FakeLLMClient([])
    with pytest.raises(DeveloperInputError):
        Developer(llm).revise(todo_plan, todo_files, [])
    assert llm.requests == []


def test_large_plans_are_written_in_batches_in_task_order(todo_plan_data):
    from app.agents.developer import file_batches
    from app.schemas.plan import ProjectPlan

    extra = ["app/a.py", "app/b.py", "app/c.py"]
    todo_plan_data["files"] += [{"path": p, "purpose": "extra"} for p in extra]
    todo_plan_data["tasks"].append(
        {"id": 99, "title": "extras", "description": "d", "files": ["app/b.py"]}
    )
    plan = ProjectPlan.model_validate(todo_plan_data)
    batches = file_batches(plan)

    assert [len(b) for b in batches] == [4, 3]
    flat = [p for b in batches for p in b]
    assert sorted(flat) == sorted(f.path for f in plan.files)
    assert flat.index("app/b.py") < flat.index("app/a.py")  # tasks first, unassigned last

    responses = [code_changes({p: f"# {p}\n" for p in b}) for b in batches]
    llm = FakeLLMClient(responses)
    call = Developer(llm).generate(plan)

    assert len(llm.requests) == 2
    assert set(call.data.as_dict()) == set(flat)
    second = llm.requests[1].user
    assert "Files already written" in second
    assert all(f'<outline path="{p}">' in second for p in batches[0])
    assert "Write exactly these files now" in second


def test_revise_may_only_change_files_with_findings(todo_plan, todo_files):
    sneaky = {"app/store.py": "# rewritten\n"}
    llm = FakeLLMClient([code_changes(sneaky), code_changes(sneaky)])
    issue = Finding(source="reviewer", **finding(file="app/main.py"))
    with pytest.raises(AgentOutputError, match="only these files may be changed"):
        Developer(llm).revise(todo_plan, todo_files, [issue])


def test_revise_batches_large_files(todo_plan, todo_files, monkeypatch):
    import app.agents.developer as developer_module
    from app.agents import common

    # A tiny budget forces one batch per file.
    monkeypatch.setattr(
        developer_module,
        "size_batches",
        lambda paths, files: common.size_batches(paths, files, budget=10),
    )
    issues = [
        Finding(source="reviewer", **finding(file="app/main.py")),
        Finding(source="ruff", **finding(file="app/store.py", severity="medium")),
    ]
    responses = [
        code_changes({"app/main.py": todo_files["app/main.py"] + "# a\n"}),
        code_changes({"app/store.py": todo_files["app/store.py"] + "# b\n"}),
    ]
    llm = FakeLLMClient(responses)
    call = Developer(llm).revise(todo_plan, todo_files, issues)

    assert len(llm.requests) == 2
    assert set(call.data.as_dict()) == {"app/main.py", "app/store.py"}
    # The second call sees the first call's updated main.py in its outline context
    assert '<outline path="app/main.py">' in llm.requests[1].user
    assert "app/store.py" in llm.requests[1].user and "[medium]" in llm.requests[1].user
