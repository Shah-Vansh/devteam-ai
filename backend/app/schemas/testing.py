"""The Tester agent's outputs: a pytest suite, and a triage of failing tests."""

from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.code import FileChange

TEST_FILE_NAMES = ("conftest.py", "__init__.py")
MAX_TEST_FILES = 6

Cause = Literal["bad_code", "bad_test", "environment"]


def is_test_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1]
    return (
        len(parts) == 2
        and parts[0] == "tests"
        and (name.startswith("test_") or name in TEST_FILE_NAMES)
    )


class TestSuite(BaseModel):
    __test__ = False  # not a pytest test class, despite the name

    files: list[FileChange] = Field(
        description="Test files under tests/: test_*.py, optionally conftest.py and __init__.py"
    )
    notes: str = Field(description="What is covered; empty if nothing to add")

    @model_validator(mode="after")
    def only_test_files(self) -> "TestSuite":
        paths = [f.path for f in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("each path may appear only once")
        if len(paths) > MAX_TEST_FILES:
            raise ValueError(f"more than {MAX_TEST_FILES} test files")
        if bad := [p for p in paths if not is_test_path(p)]:
            raise ValueError(f"only files directly under tests/ may be written: {bad}")
        return self

    def as_dict(self) -> dict[str, str]:
        return {f.path: f.content for f in self.files}


class TriageItem(BaseModel):
    test: str = Field(description="Failing test name exactly as given")
    cause: Cause = Field(
        description="bad_code: the application is wrong; bad_test: the test expects something "
        "the plan does not require or is written incorrectly; environment: a missing package, "
        "network or sandbox problem that neither code nor test changes can fix"
    )
    file: str = Field(
        description="File that must change: an app file for bad_code, a test file for "
        "bad_test, empty for environment"
    )
    reason: str = Field(description="Why, citing the error message")
    suggested_fix: str = Field(description="Concrete change to make")


class FailureTriage(BaseModel):
    items: list[TriageItem]
    summary: str = Field(description="One or two sentences")
