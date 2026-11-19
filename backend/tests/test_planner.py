import pytest

from app.agents.planner import MAX_REQUIREMENT_CHARS, Planner, PlannerInputError
from app.llm.base import LLMResponseError
from app.llm.fake import FakeLLMClient
from app.schemas.plan import Clarification, ProjectPlan


def test_plan_returns_validated_plan(todo_plan_data):
    llm = FakeLLMClient(responses=[todo_plan_data])
    result = Planner(llm).plan("Build a todo API")
    assert isinstance(result.plan, ProjectPlan)
    assert result.plan.project_name == "todo-api"
    request = llm.requests[0]
    assert request.agent == "planner"
    assert request.schema is ProjectPlan
    assert "You are the Planner" in request.system


def test_requirement_is_wrapped_as_data(todo_plan_data):
    llm = FakeLLMClient(responses=[todo_plan_data])
    Planner(llm).plan("Build a todo API")
    assert llm.requests[0].user == "<requirement>\nBuild a todo API\n</requirement>"


def test_clarifications_are_included(todo_plan_data):
    llm = FakeLLMClient(responses=[todo_plan_data])
    answers = [Clarification(question="Persist data?", answer="No, memory is fine.")]
    Planner(llm).plan("Build a todo API", answers)
    user = llm.requests[0].user
    assert "<clarifications>" in user
    assert "Q: Persist data?\nA: No, memory is fine." in user


@pytest.mark.parametrize("requirement", ["", "   ", "x" * (MAX_REQUIREMENT_CHARS + 1)])
def test_invalid_requirement_makes_no_llm_call(requirement):
    llm = FakeLLMClient(responses=[])
    with pytest.raises(PlannerInputError):
        Planner(llm).plan(requirement)
    assert llm.requests == []


def test_llm_errors_propagate():
    llm = FakeLLMClient(responses=[LLMResponseError("bad output")])
    with pytest.raises(LLMResponseError):
        Planner(llm).plan("Build a todo API")
