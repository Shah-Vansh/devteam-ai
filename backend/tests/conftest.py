import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def todo_plan_data() -> dict:
    """A valid plan as the model would return it (a fresh copy for each test)."""
    return json.loads((FIXTURES / "plan_todo.json").read_text(encoding="utf-8"))


TODO_FILES = {
    "app/main.py": (
        "from fastapi import FastAPI, HTTPException\n"
        "\n"
        "from app.schemas import Todo, TodoCreate\n"
        "from app.store import store\n"
        "\n"
        'app = FastAPI(title="Todo API")\n'
        "\n"
        "\n"
        '@app.post("/todos", status_code=201)\n'
        "def create_todo(body: TodoCreate) -> Todo:\n"
        "    return store.add(body.title)\n"
        "\n"
        "\n"
        '@app.get("/todos")\n'
        "def list_todos() -> list[Todo]:\n"
        "    return store.all()\n"
        "\n"
        "\n"
        '@app.delete("/todos/{todo_id}", status_code=204)\n'
        "def delete_todo(todo_id: int) -> None:\n"
        "    if not store.delete(todo_id):\n"
        '        raise HTTPException(status_code=404, detail="todo not found")\n'
    ),
    "app/schemas.py": (
        "from pydantic import BaseModel\n"
        "\n"
        "\n"
        "class TodoCreate(BaseModel):\n"
        "    title: str\n"
        "\n"
        "\n"
        "class Todo(TodoCreate):\n"
        "    id: int\n"
    ),
    "app/store.py": (
        "from app.schemas import Todo\n"
        "\n"
        "\n"
        "class Store:\n"
        "    def __init__(self) -> None:\n"
        "        self.items: dict[int, Todo] = {}\n"
        "        self.next_id = 1\n"
        "\n"
        "    def add(self, title: str) -> Todo:\n"
        "        todo = Todo(id=self.next_id, title=title)\n"
        "        self.items[todo.id] = todo\n"
        "        self.next_id += 1\n"
        "        return todo\n"
        "\n"
        "    def all(self) -> list[Todo]:\n"
        "        return list(self.items.values())\n"
        "\n"
        "    def delete(self, todo_id: int) -> bool:\n"
        "        return self.items.pop(todo_id, None) is not None\n"
        "\n"
        "\n"
        "store = Store()\n"
    ),
    "requirements.txt": "fastapi\nuvicorn\n",
}


@pytest.fixture
def todo_plan(todo_plan_data):
    from app.schemas.plan import ProjectPlan

    return ProjectPlan.model_validate(todo_plan_data)


@pytest.fixture
def todo_files() -> dict[str, str]:
    """Correct code for the todo plan, as the Developer would return it."""
    return dict(TODO_FILES)


def code_changes(files: dict[str, str]) -> dict:
    """A CodeChanges response as the model would return it."""
    return {
        "files": [
            {"path": p, "content": c, "reason": "implements the plan"} for p, c in files.items()
        ],
        "notes": "",
    }


def review_output(*findings: dict, summary: str = "Looks reasonable.") -> dict:
    return {"summary": summary, "findings": list(findings)}


def finding(file="app/main.py", line=1, severity="high", category="bug", message="broken") -> dict:
    return {
        "file": file,
        "line": line,
        "severity": severity,
        "category": category,
        "message": message,
        "suggested_fix": "fix it",
    }
