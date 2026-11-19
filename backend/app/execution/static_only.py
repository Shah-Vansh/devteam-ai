"""The executor used when no sandbox is configured: it never runs anything.

Static analysis already happens during review. This executor only checks that the
test files parse, then reports `NOT_EXECUTED`, never a pass.
"""

import ast

from app.execution.base import ExecutionResult, ExecutionSpec


class StaticOnlyExecutor:
    name = "static_only"

    def __init__(self, reason: str = "no sandbox configured") -> None:
        self._reason = reason

    def run_tests(self, files: dict[str, str], spec: ExecutionSpec) -> ExecutionResult:
        broken = []
        for path, content in files.items():
            if path.endswith(".py"):
                try:
                    ast.parse(content)
                except SyntaxError as exc:
                    broken.append(f"{path}:{exc.lineno}")
        detail = f"tests were not run: {self._reason}"
        if broken:
            detail += f"; files with syntax errors: {', '.join(broken)}"
        return ExecutionResult(status="NOT_EXECUTED", executor=self.name, detail=detail)
