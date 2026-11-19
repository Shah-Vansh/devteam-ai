"""CLI behaviour around human pauses."""

import builtins

import pytest

from app import cli


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def terminal(monkeypatch):
    """Pretend stdin is a terminal and script what the user types."""
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True, raising=False)
    answers: list[object] = []

    def fake_input(_prompt=""):
        value = answers.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr(builtins, "input", fake_input)
    return answers


@pytest.mark.anyio
async def test_eof_at_a_prompt_leaves_the_run_paused(terminal):
    # Windows: stdin redirected from NUL claims to be a terminal, then gives EOF.
    terminal.append(EOFError())
    assert await cli.ask_human({"kind": "execute", "executor": "e2b"}) is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("typed", "reply"),
    [
        ("y", {"approved": True}),
        ("YES", {"approved": True}),
        ("", {"approved": False}),
        ("n", {"approved": False}),
        ("cancel", {"action": "cancel"}),
        ("later", None),
    ],
)
async def test_execution_prompt_answers(terminal, typed, reply):
    terminal.append(typed)
    assert await cli.ask_human({"kind": "execute", "executor": "e2b"}) == reply


@pytest.mark.anyio
async def test_clarification_prompt_collects_answers(terminal):
    terminal.extend(["Yes, reject duplicates", ""])
    pause = {"kind": "clarify", "questions": ["Unique titles?", "Persist data?"]}
    assert await cli.ask_human(pause) == {"answers": ["Yes, reject duplicates", ""]}


@pytest.mark.anyio
async def test_clarification_can_be_postponed_or_cancelled(terminal):
    pause = {"kind": "clarify", "questions": ["Unique titles?"]}
    terminal.append("later")
    assert await cli.ask_human(pause) is None
    terminal.append("cancel")
    assert await cli.ask_human(pause) == {"action": "cancel"}


def test_auto_replies_keep_assumptions_and_approve():
    assert cli.AUTO_REPLIES == {"clarify": {"answers": []}, "execute": {"approved": True}}


def test_run_ids_sort_by_time_and_are_unique():
    ids = [cli.new_run_id() for _ in range(5)]
    assert len(set(ids)) == 5
    assert all(len(i.split("-")) == 3 for i in ids)
