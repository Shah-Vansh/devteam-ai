"""The Developer agent's output: whole files, never patches.

Whole files are easier for a model to get right than diffs, and they are small here
(at most 20 files, 100 KB each). Workflow code writes them through the Filesystem MCP
server; the Developer itself never touches the disk.
"""

from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.plan import MAX_FILES, check_relative_path

MAX_FILE_CHARS = 100_000


class FileChange(BaseModel):
    path: str = Field(description="Relative path with forward slashes, e.g. app/main.py")
    content: str = Field(description="The complete file content, not a diff")
    reason: str = Field(description="One sentence: what this file does or what changed")

    @field_validator("path")
    @classmethod
    def path_is_safe(cls, value: str) -> str:
        return check_relative_path(value)

    @field_validator("content")
    @classmethod
    def content_size(cls, value: str) -> str:
        if len(value) > MAX_FILE_CHARS:
            raise ValueError(f"file content longer than {MAX_FILE_CHARS} characters")
        # Seen live: a model wrote requirements.txt as one line containing the two
        # characters backslash and n, so every package was hidden inside a comment.
        if "\\n" in value and "\n" not in value.strip():
            raise ValueError(
                "file content contains literal \\n sequences instead of real line breaks"
            )
        return value

    @model_validator(mode="after")
    def not_empty(self) -> "FileChange":
        # Package markers are legitimately empty; any other empty file is a lazy answer.
        if not self.content.strip() and PurePosixPath(self.path).name != "__init__.py":
            raise ValueError(f"file content is empty: {self.path}")
        return self


class CodeChanges(BaseModel):
    files: list[FileChange] = Field(description="Files to create or replace, full content each")
    notes: str = Field(description="Anything the reviewer should know; empty if nothing")

    @model_validator(mode="after")
    def consistent(self) -> "CodeChanges":
        if len(self.files) > MAX_FILES:
            raise ValueError(f"more than {MAX_FILES} files")
        paths = [f.path for f in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("each path may appear only once")
        if any(PurePosixPath(p).name.startswith("test_") for p in paths):
            raise ValueError("test files are written by the Tester, not the Developer")
        return self

    def as_dict(self) -> dict[str, str]:
        return {f.path: f.content for f in self.files}
