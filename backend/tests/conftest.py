import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def todo_plan_data() -> dict:
    """A valid plan as the model would return it (a fresh copy for each test)."""
    return json.loads((FIXTURES / "plan_todo.json").read_text(encoding="utf-8"))
