"""Packages, JUnit parsing and executors. The E2B executor is tested with a fake sandbox
that records every call, so the order of the security steps can be asserted."""

import pytest
from e2b import CommandExitException, TimeoutException

from app.core.config import Settings
from app.execution.base import ExecutionSpec
from app.execution.e2b_executor import E2BExecutor
from app.execution.factory import build_executor
from app.execution.junit import ReportError, parse_junit
from app.execution.packages import (
    ALLOWED_PACKAGES,
    CONSTRAINTS_FILE,
    normalize,
    packages_rule,
    select_packages,
)
from app.execution.static_only import StaticOnlyExecutor

# ---------- packages ----------


def test_select_packages_ignores_versions_and_adds_test_tools():
    selection = select_packages(
        "fastapi>=0.100\nUvicorn[standard]==0.30\n# comment\n\npython_jose\npasslib[bcrypt]\n"
    )
    assert selection.install == [
        "fastapi",
        "uvicorn",
        "python-jose[cryptography]",
        "passlib[bcrypt]",
        "pytest",
        "httpx",
    ]
    assert selection.rejected == []


@pytest.mark.parametrize(
    "line",
    [
        "requests",
        "psycopg2-binary",
        "-r other.txt",
        "--index-url https://evil.test",
        "git+https://x",
    ],
)
def test_select_packages_rejects_unknown_names_and_options(line):
    selection = select_packages(f"fastapi\n{line}\n")
    assert selection.rejected == [line]
    assert "fastapi" in selection.install


def test_constraints_file_pins_every_allowed_package():
    pins = {}
    for line in CONSTRAINTS_FILE.read_text(encoding="utf-8").splitlines():
        if "==" in line and not line.startswith("#"):
            name, version = line.split("==")
            pins[normalize(name)] = version
    for name in [*ALLOWED_PACKAGES, "pytest", "httpx", "starlette", "anyio"]:
        assert name in pins, f"{name} is not pinned"
    assert pins["bcrypt"] == "4.0.1"  # passlib compatibility override


def test_prompt_rule_lists_the_allowed_packages():
    rule = packages_rule()
    assert all(name in rule for name in ALLOWED_PACKAGES)


# ---------- JUnit ----------

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4">
  <testcase classname="tests.test_todos" name="test_ok" time="0.01"/>
  <testcase classname="tests.test_todos" name="test_bad" time="0.01">
    <failure message="assert 200 == 201">long traceback</failure>
  </testcase>
  <testcase classname="tests.test_todos.TestDelete" name="test_err">
    <error message="fixture failed">trace</error>
  </testcase>
  <testcase classname="tests.test_other" name="test_skip"><skipped message="later"/></testcase>
</testsuite></testsuites>"""


def test_parse_junit_outcomes_names_and_messages():
    cases = parse_junit(JUNIT)
    assert [(c.name, c.outcome) for c in cases] == [
        ("tests/test_todos.py::test_ok", "passed"),
        ("tests/test_todos.py::test_bad", "failed"),
        ("tests/test_todos.py::test_err", "error"),
        ("tests/test_other.py::test_skip", "skipped"),
    ]
    assert cases[1].message.startswith("assert 200 == 201")
    assert "long traceback" in cases[1].message


def test_parse_junit_refuses_entity_expansion():
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><testsuites>&b;</testsuites>'
    )
    with pytest.raises(ReportError):
        parse_junit(bomb)


def test_parse_junit_refuses_huge_and_broken_reports():
    with pytest.raises(ReportError, match="too large"):
        parse_junit("<a>" + "x" * 2_000_001 + "</a>")
    with pytest.raises(ReportError):
        parse_junit("<testsuites><testcase")


# ---------- static-only executor and factory ----------


def test_static_only_never_claims_a_pass():
    result = StaticOnlyExecutor().run_tests(
        {"tests/test_a.py": "def test_x(:\n", "app/main.py": "x = 1\n"}, ExecutionSpec()
    )
    assert result.status == "NOT_EXECUTED"
    assert result.passed == 0
    assert "tests/test_a.py:1" in result.detail


def settings(**values) -> Settings:
    return Settings(_env_file=None, **values)


def test_factory_picks_executor():
    assert build_executor(settings(executor="static_only")).name == "static_only"
    no_key = build_executor(settings(executor="e2b", e2b_api_key=None))
    assert no_key.name == "static_only"
    assert "E2B_API_KEY" in no_key.run_tests({}, ExecutionSpec()).detail
    assert build_executor(settings(executor="e2b", e2b_api_key="k")).name == "e2b"


# ---------- E2B executor with a fake sandbox ----------


class FakeSandbox:
    def __init__(self, *, install_error=None, pytest_outcome=None, report=JUNIT):
        self.log: list[str] = []
        self.written: dict[str, str] = {}
        self.install_error = install_error
        self.pytest_outcome = pytest_outcome
        self.report = report
        self.files = self
        self.commands = self

    # files
    def write(self, path, data):
        self.log.append(f"write {path}")
        self.written[path] = data

    def read(self, path):
        self.log.append(f"read {path}")
        return self.report

    # commands
    def run(self, cmd, cwd=None, timeout=None):
        if cmd.startswith("pip install"):
            self.log.append("install")
            assert "-c /home/user/constraints.txt" in cmd
            if self.install_error:
                raise self.install_error
        elif "pytest" in cmd:
            self.log.append(f"pytest cwd={cwd}")
            if isinstance(self.pytest_outcome, Exception):
                raise self.pytest_outcome
        return type("R", (), {"stdout": "out", "stderr": ""})()

    def update_network(self, network):
        self.log.append(f"network {network}")

    def kill(self):
        self.log.append("kill")


def run_fake(sandbox, files=None):
    created = {}

    def factory(**kwargs):
        created.update(kwargs)
        return sandbox

    executor = E2BExecutor("key", sandbox_factory=factory)
    files = files or {"app/main.py": "x = 1\n", "tests/test_a.py": "def test_a(): pass\n"}
    result = executor.run_tests(
        files, ExecutionSpec(packages=["fastapi", "pytest"], timeout_seconds=30)
    )
    return result, created


def failed_exit(code=1):
    return CommandExitException(stderr="", stdout="1 failed", exit_code=code, error=None)


def test_security_steps_happen_in_order_and_sandbox_is_killed():
    sandbox = FakeSandbox(pytest_outcome=failed_exit())
    result, created = run_fake(sandbox)

    assert "envs" not in created  # no secrets or environment passed into the sandbox
    log = sandbox.log
    assert log.index("install") < log.index("network {'allow_internet_access': False}")
    assert log.index("network {'allow_internet_access': False}") < log.index(
        "pytest cwd=/home/user/project"
    )
    assert log[-1] == "kill"
    assert "/home/user/project/app/main.py" in sandbox.written
    assert result.status == "FAILED"
    assert (result.passed, result.failed, result.errors, result.skipped) == (1, 1, 1, 1)


def test_all_passing():
    report = '<testsuites><testcase classname="tests.test_a" name="test_a"/></testsuites>'
    result, _ = run_fake(FakeSandbox(report=report))
    assert result.status == "PASSED"
    assert result.passed == 1


def test_install_failure_is_an_error_and_tests_never_run():
    sandbox = FakeSandbox(install_error=failed_exit())
    result, _ = run_fake(sandbox)
    assert result.status == "ERROR"
    assert result.detail == "package installation failed"
    assert not any(entry.startswith("pytest") for entry in sandbox.log)
    assert sandbox.log[-1] == "kill"


def test_timeout_is_an_error_and_sandbox_is_still_killed():
    sandbox = FakeSandbox(pytest_outcome=TimeoutException("slow"))
    result, _ = run_fake(sandbox)
    assert result.status == "ERROR"
    assert "timed out" in result.detail
    assert sandbox.log[-1] == "kill"


def test_no_tests_collected_becomes_a_failing_case():
    sandbox = FakeSandbox(pytest_outcome=failed_exit(5), report="<testsuites/>")
    result, _ = run_fake(sandbox)
    assert result.status == "FAILED"
    assert [c.name for c in result.failures] == ["pytest::session"]
    assert "no tests were collected" in result.failures[0].message


def test_unsafe_path_is_refused_before_creating_a_sandbox():
    created = []
    executor = E2BExecutor("key", sandbox_factory=lambda **kw: created.append(kw))
    result = executor.run_tests({"../escape.py": "x"}, ExecutionSpec())
    assert result.status == "ERROR"
    assert created == []
