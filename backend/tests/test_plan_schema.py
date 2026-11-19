import pytest
from pydantic import ValidationError

from app.schemas.plan import ProjectPlan


def test_valid_plan_parses(todo_plan_data):
    plan = ProjectPlan.model_validate(todo_plan_data)
    assert plan.project_name == "todo-api"  # slugified from "Todo API"
    assert len(plan.files) == 4


@pytest.mark.parametrize(
    "bad_path",
    ["/etc/passwd", "../secrets.py", "app/../../x.py", "C:/x.py", "app\\main.py", "run.sh", ""],
)
def test_unsafe_or_disallowed_paths_are_rejected(todo_plan_data, bad_path):
    todo_plan_data["files"][0]["path"] = bad_path
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(todo_plan_data)


def test_task_must_reference_planned_files(todo_plan_data):
    todo_plan_data["tasks"][0]["files"] = ["app/missing.py"]
    with pytest.raises(ValidationError, match="unplanned files"):
        ProjectPlan.model_validate(todo_plan_data)


def test_duplicate_paths_rejected(todo_plan_data):
    todo_plan_data["files"].append({"path": "app/main.py", "purpose": "again"})
    with pytest.raises(ValidationError, match="unique"):
        ProjectPlan.model_validate(todo_plan_data)


def test_test_files_are_not_allowed_in_plan(todo_plan_data):
    todo_plan_data["files"].append({"path": "tests/test_main.py", "purpose": "tests"})
    with pytest.raises(ValidationError, match="Tester"):
        ProjectPlan.model_validate(todo_plan_data)


def test_duplicate_task_ids_rejected(todo_plan_data):
    todo_plan_data["tasks"][1]["id"] = 1
    with pytest.raises(ValidationError, match="unique ids"):
        ProjectPlan.model_validate(todo_plan_data)
