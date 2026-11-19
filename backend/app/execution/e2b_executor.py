"""Run a project's tests in a fresh E2B microVM.

Order matters (Spike A, docs/EXECUTION_SANDBOX.md):
1. create a new sandbox, passing no environment variables (no secrets inside);
2. upload only the project files and the constraints file;
3. install allowed packages, pinned by the constraints file (internet on);
4. switch internet OFF;
5. run pytest with a JUnit XML report and a timeout;
6. read the report; kill the sandbox in `finally`, whatever happened.
"""

import shlex
import time
from collections.abc import Callable
from typing import Any

from e2b import CommandExitException, Sandbox, SandboxException, TimeoutException

from app.execution.base import ExecutionResult, ExecutionSpec, TestCaseResult, tail
from app.execution.junit import ReportError, parse_junit
from app.execution.packages import CONSTRAINTS_FILE
from app.workspace.paths import validate_relative_path

HOME = "/home/user"
PROJECT_DIR = f"{HOME}/project"
REPORT_PATH = f"{HOME}/report.xml"
CONSTRAINTS_PATH = f"{HOME}/constraints.txt"
INSTALL_TIMEOUT_SECONDS = 240

# pytest exit codes: 0 all passed, 1 some failed, 2 interrupted (often collection errors),
# 3 internal error, 4 usage error, 5 no tests collected.
NO_TESTS_COLLECTED = 5


class E2BExecutor:
    name = "e2b"

    def __init__(
        self,
        api_key: str,
        *,
        sandbox_factory: Callable[..., Any] = Sandbox.create,
        install_timeout_seconds: int = INSTALL_TIMEOUT_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._create = sandbox_factory
        self._install_timeout = install_timeout_seconds

    def run_tests(self, files: dict[str, str], spec: ExecutionSpec) -> ExecutionResult:
        start = time.perf_counter()

        def result(status, **kwargs) -> ExecutionResult:
            elapsed = int((time.perf_counter() - start) * 1000)
            return ExecutionResult(status=status, executor=self.name, duration_ms=elapsed, **kwargs)

        sandbox = None
        try:
            for path in files:
                validate_relative_path(path)  # nothing outside the project folder
            sandbox = self._create(
                api_key=self._api_key,
                timeout=spec.timeout_seconds + self._install_timeout + 60,  # backstop
            )
            for path, content in files.items():
                sandbox.files.write(f"{PROJECT_DIR}/{path}", content)
            sandbox.files.write(CONSTRAINTS_PATH, CONSTRAINTS_FILE.read_text(encoding="utf-8"))

            packages = " ".join(shlex.quote(p) for p in spec.packages)
            try:
                sandbox.commands.run(
                    "pip install --no-input --disable-pip-version-check -q "
                    f"-c {CONSTRAINTS_PATH} {packages}",
                    timeout=self._install_timeout,
                )
            except CommandExitException as exc:
                return result(
                    "ERROR",
                    detail="package installation failed",
                    output_tail=tail(f"{exc.stdout}\n{exc.stderr}"),
                )

            sandbox.update_network({"allow_internet_access": False})

            try:
                run = sandbox.commands.run(
                    f"python -m pytest -q -p no:cacheprovider --junitxml={REPORT_PATH}",
                    cwd=PROJECT_DIR,
                    timeout=spec.timeout_seconds,
                )
                exit_code, output = 0, f"{run.stdout}\n{run.stderr}"
            except CommandExitException as exc:
                exit_code, output = exc.exit_code, f"{exc.stdout}\n{exc.stderr}"

            try:
                cases = parse_junit(sandbox.files.read(REPORT_PATH))
            except (ReportError, SandboxException):
                cases = []
            return result(**summarise(cases, exit_code, output))

        except TimeoutException:
            return result("ERROR", detail=f"timed out (limit {spec.timeout_seconds}s for tests)")
        except SandboxException as exc:
            return result("ERROR", detail=f"sandbox error: {type(exc).__name__}: {exc}"[:500])
        except ValueError as exc:  # a path rejected before anything was uploaded
            return result("ERROR", detail=str(exc))
        finally:
            if sandbox is not None:
                try:
                    sandbox.kill()
                except Exception:  # noqa: S110 - the sandbox also expires on its own timeout
                    pass


def summarise(cases: list[TestCaseResult], exit_code: int, output: str) -> dict:
    """Counts and status from parsed cases plus pytest's exit code.

    A non-zero exit with no failing case in the report (collection error, no tests found)
    becomes one synthetic failing case, so triage always has something to look at."""
    counts = {
        k: sum(c.outcome == k for c in cases) for k in ("passed", "failed", "error", "skipped")
    }
    if exit_code != 0 and counts["failed"] + counts["error"] == 0:
        message = "no tests were collected" if exit_code == NO_TESTS_COLLECTED else output
        cases = [
            *cases,
            TestCaseResult(name="pytest::session", outcome="error", message=tail(message, 2000)),
        ]
        counts["error"] += 1
    passed_all = exit_code == 0 and counts["passed"] > 0
    return {
        "status": "PASSED" if passed_all else "FAILED",
        "passed": counts["passed"],
        "failed": counts["failed"],
        "errors": counts["error"],
        "skipped": counts["skipped"],
        "cases": cases,
        "output_tail": tail(output),
    }
