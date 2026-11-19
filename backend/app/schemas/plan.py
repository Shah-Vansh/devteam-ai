"""The Planner agent's output.

Two layers of validation:
- The *schema* (field names and types) is sent to the model as a strict JSON schema,
  so the provider forces the shape.
- The *validators* below enforce rules a JSON schema cannot express well (safe
  relative paths, tasks only referencing planned files). They run when the reply
  is parsed; a failure triggers one more attempt in the LLM client.
"""

import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ALLOWED_EXTENSIONS = {".py", ".txt", ".md", ".toml", ".ini", ".cfg", ".json", ".yaml", ".yml"}
MAX_FILES = 20


def check_relative_path(path: str) -> str:
    """A generated path must stay inside the project workspace."""
    if not path or "\\" in path or ":" in path or path.startswith("/"):
        raise ValueError(f"path must be relative and use '/': {path!r}")
    parts = PurePosixPath(path).parts
    if ".." in parts or "." in parts:
        raise ValueError(f"path must not contain '.' or '..' segments: {path!r}")
    if PurePosixPath(path).suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"file type not allowed: {path!r}")
    return path


class PlannedFile(BaseModel):
    path: str = Field(description="Relative path with forward slashes, e.g. app/main.py")
    purpose: str = Field(description="One sentence: what this file contains")

    @field_validator("path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return check_relative_path(value)


class PlanTask(BaseModel):
    id: int = Field(description="Task number starting at 1")
    title: str
    description: str = Field(description="What to implement, concrete enough for a developer")
    files: list[str] = Field(description="Paths from the plan's files list this task touches")


class ProjectPlan(BaseModel):
    project_name: str = Field(description="Short lowercase name with hyphens, e.g. todo-api")
    summary: str = Field(description="Two or three sentences describing the application")
    features: list[str]
    files: list[PlannedFile] = Field(description="Application files only, no test files")
    tasks: list[PlanTask]
    dependencies: list[str] = Field(description="pip package names the application needs")
    assumptions: list[str] = Field(description="Decisions made where the requirement was silent")
    open_questions: list[str] = Field(
        description="Only questions whose answer would change the design; may be empty"
    )
    complexity: Literal["small", "medium", "large"]

    @field_validator("project_name")
    @classmethod
    def slugify_name(cls, value: str) -> str:
        """Accept 'Todo API' from the model but store 'todo-api'."""
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        if not slug:
            raise ValueError("project_name is empty after normalisation")
        return slug[:50]

    @model_validator(mode="after")
    def check_consistency(self) -> "ProjectPlan":
        paths = [f.path for f in self.files]
        if not paths:
            raise ValueError("plan must contain at least one file")
        if len(paths) > MAX_FILES:
            raise ValueError(f"plan has {len(paths)} files; maximum is {MAX_FILES}")
        if len(set(paths)) != len(paths):
            raise ValueError("file paths must be unique")
        if any(PurePosixPath(p).name.startswith("test_") for p in paths):
            raise ValueError("test files belong to the Tester agent, not the plan")

        ids = [t.id for t in self.tasks]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("tasks must exist and have unique ids")
        known = set(paths)
        for task in self.tasks:
            unknown = [p for p in task.files if p not in known]
            if unknown:
                raise ValueError(f"task {task.id} references unplanned files: {unknown}")
        return self


class Clarification(BaseModel):
    question: str
    answer: str
