import pytest
from pydantic import BaseModel

from app.agents.common import AgentOutputError, files_block, generate_checked
from app.llm.fake import FakeLLMClient


class Answer(BaseModel):
    value: int


def run(llm, check):
    return generate_checked(llm, system="s", user="u", schema=Answer, agent="t", check=check)


def test_no_retry_when_check_passes():
    llm = FakeLLMClient([{"value": 1}])
    call = run(llm, lambda a: [])
    assert call.data.value == 1
    assert len(llm.requests) == 1


def test_retry_includes_the_problems_then_succeeds():
    llm = FakeLLMClient([{"value": -1}, {"value": 2}])
    call = run(llm, lambda a: ["value must be positive"] if a.value < 0 else [])
    assert call.data.value == 2
    assert len(call.usages) == 2
    assert "- value must be positive" in llm.requests[1].user
    assert llm.requests[1].user.startswith("u")


def test_second_failure_raises_with_problems():
    llm = FakeLLMClient([{"value": -1}, {"value": -2}])
    with pytest.raises(AgentOutputError) as info:
        run(llm, lambda a: ["value must be positive"])
    assert info.value.problems == ["value must be positive"]


def test_files_block_numbers_lines_and_sorts_paths():
    block = files_block({"b.py": "x\ny", "a.py": "z"}, numbered=True)
    assert block.index('path="a.py"') < block.index('path="b.py"')
    assert "   1 | x\n   2 | y" in block
