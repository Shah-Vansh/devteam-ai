import subprocess

from app.analysis import static
from app.analysis.static import analyze


def rules(report):
    return {(f.source, f.rule, f.file) for f in report.findings}


def test_clean_code_has_no_blocking_findings(todo_files):
    report = analyze(todo_files)
    assert report.tools_run == ["python", "ruff", "bandit"]
    assert report.tools_failed == {}
    assert report.syntax_ok
    assert [f for f in report.findings if f.severity == "high"] == []


def test_syntax_error_is_reported_once_as_high():
    report = analyze({"app/bad.py": "def f(:\n    pass\n"})
    syntax = [f for f in report.findings if f.file == "app/bad.py"]
    assert len(syntax) == 1
    assert (syntax[0].source, syntax[0].severity, syntax[0].line) == ("python", "high", 1)
    assert not report.syntax_ok


def test_undefined_name_is_high():
    report = analyze({"app/main.py": "def f():\n    return missing_name\n"})
    (item,) = [f for f in report.findings if f.rule == "F821"]
    assert (item.severity, item.line, item.file) == ("high", 2, "app/main.py")


def test_unused_import_is_low():
    report = analyze({"app/main.py": "import os\n"})
    assert [(f.rule, f.severity) for f in report.findings] == [("F401", "low")]


def test_shell_injection_risk_is_high_security():
    code = "import subprocess\n\n\ndef run(cmd):\n    subprocess.call(cmd, shell=True)\n"
    report = analyze({"app/run.py": code})
    (item,) = [f for f in report.findings if f.rule == "B602"]
    assert (item.source, item.severity, item.category, item.line) == (
        "bandit",
        "high",
        "security",
        5,
    )


def test_fastapi_depends_default_is_not_flagged():
    code = (
        "from fastapi import Depends, FastAPI\n\napp = FastAPI()\n\n\n"
        "def db():\n    return 1\n\n\n"
        '@app.get("/")\ndef root(x: int = Depends(db)) -> int:\n    return x\n'
    )
    assert not any(f.rule == "B008" for f in analyze({"app/main.py": code}).findings)


def test_non_python_files_are_ignored():
    report = analyze({"requirements.txt": "fastapi\n", "README.md": "# hi\n"})
    assert report.findings == []
    assert report.tools_run == ["python"]


def test_project_config_cannot_switch_rules_off(todo_files):
    # A generated pyproject could try to disable checks; only .py files are analysed
    # and ruff runs with --isolated.
    files = {**todo_files, "pyproject.toml": "[tool.ruff]\nlint.ignore = ['F']\n"}
    files["app/extra.py"] = "import os\n"
    assert ("ruff", "F401", "app/extra.py") in rules(analyze(files))


def test_a_failing_tool_is_reported_not_raised(monkeypatch):
    def broken(args, cwd):
        if args[0] == "bandit":
            raise subprocess.TimeoutExpired(cmd="bandit", timeout=60)
        return original(args, cwd)

    original = static._run
    monkeypatch.setattr(static, "_run", broken)
    report = analyze({"app/main.py": "import os\n"})
    assert report.tools_run == ["python", "ruff"]
    assert "bandit" in report.tools_failed
