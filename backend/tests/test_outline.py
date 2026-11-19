from app.agents.common import size_batches
from app.analysis.outline import outline_file, outline_python

SOURCE = """
import os
from fastapi import APIRouter, HTTPException

from app.schemas import Todo

router = APIRouter(prefix="/todos")
SECRET_TEXT = "a very long string value that should be shortened in the outline output ok"


class TodoStore:
    items: dict[int, Todo]

    def add(self, title: str) -> Todo:
        todo = Todo(id=1, title=title)
        return todo


@router.get("/{todo_id}")
async def get_todo(todo_id: int) -> Todo:
    raise HTTPException(status_code=404)
"""


def test_outline_keeps_interfaces_and_drops_bodies():
    text = outline_python(SOURCE)
    assert "from fastapi import APIRouter, HTTPException" in text
    assert "router = APIRouter(prefix='/todos')" in text
    assert "class TodoStore():" in text
    assert "    items: dict[int, Todo]" in text
    assert "    def add(self, title: str) -> Todo: ..." in text
    assert "@router.get('/{todo_id}')" in text
    assert "async def get_todo(todo_id: int) -> Todo: ..." in text
    assert "todo = Todo(" not in text  # bodies removed
    assert "..." in text.split("SECRET_TEXT = ")[1].splitlines()[0]  # long values shortened
    assert len(text) < len(SOURCE)


def test_outline_of_broken_or_empty_python():
    assert "could not parse" in outline_python("def f(:\n")
    assert outline_python("") == "# (empty module)"


def test_outline_of_text_files_is_the_first_lines():
    content = "\n".join(f"pkg{i}" for i in range(30))
    text = outline_file("requirements.txt", content)
    assert text.splitlines()[0] == "pkg0"
    assert text.endswith("(15 more lines)")


def test_size_batches_respects_budget_and_order():
    files = {"a": "x" * 5, "b": "x" * 5, "c": "x" * 20, "d": "x"}
    assert size_batches(["a", "b", "c", "d"], files, budget=10) == [["a", "b"], ["c"], ["d"]]
    assert size_batches([], files) == []
