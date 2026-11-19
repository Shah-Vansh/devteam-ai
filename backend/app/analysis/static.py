"""Static analysis of generated code: Python's own parser, ruff and bandit.

None of these tools runs the code. They only parse it, so running them on the host is
safe (threat T1 in SECURITY_DESIGN.md); executing code is left to the sandbox (Phase 4).

Files are copied into a fresh temporary folder, so analysis needs only the file
contents, not a workspace path. Tools run with fixed arguments, without a shell, and
ignore any configuration files the generated project might contain (`--isolated`).
A tool that is missing or fails is reported, not raised, so a review can still happen.
"""

import ast
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app.schemas.review import Finding
from app.workspace.paths import validate_relative_path

TOOL_TIMEOUT_SECONDS = 60

# Ruff rules: E9 = syntax/IO errors, F = pyflakes (undefined names, unused imports ...),
# B = bugbear (likely bugs). B008 is ignored: FastAPI's `Depends()` in defaults is idiomatic.
RUFF_SELECT = "E9,F,B"
RUFF_IGNORE = "B008"
RULE_CODE = re.compile(r"[A-Z]+[0-9]+")
RUFF_HIGH = {"F821", "F822", "F823", "F811", "F632", "F701", "F702", "F704", "F706"}

BANDIT_SEVERITY = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}


@dataclass
class StaticReport:
    findings: list[Finding] = field(default_factory=list)
    tools_run: list[str] = field(default_factory=list)
    tools_failed: dict[str, str] = field(default_factory=dict)

    @property
    def syntax_ok(self) -> bool:
        return not any(f.source == "python" for f in self.findings)


def analyze(files: dict[str, str]) -> StaticReport:
    report = StaticReport()
    python_files = {p: c for p, c in files.items() if p.endswith(".py")}

    report.findings.extend(_syntax_findings(python_files))
    report.tools_run.append("python")
    if not python_files:
        return report

    with tempfile.TemporaryDirectory(prefix="devteam-sa-") as tmp:
        root = Path(tmp)
        for path, content in python_files.items():
            validate_relative_path(path)  # never write outside the temp folder
            target = root.joinpath(*path.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="")

        for name, runner in (("ruff", _run_ruff), ("bandit", _run_bandit)):
            try:
                report.findings.extend(runner(root))
                report.tools_run.append(name)
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                report.tools_failed[name] = f"{type(exc).__name__}: {exc}"[:300]

    report.findings.sort(key=lambda f: (f.file, f.line))
    return report


def _syntax_findings(python_files: dict[str, str]) -> list[Finding]:
    findings = []
    for path, content in python_files.items():
        try:
            ast.parse(content, filename=path)
        except SyntaxError as exc:
            findings.append(
                Finding(
                    source="python",
                    rule="SyntaxError",
                    file=path,
                    line=exc.lineno or 0,
                    severity="high",
                    category="bug",
                    message=f"syntax error: {exc.msg}",
                    suggested_fix="Fix the syntax so the file can be imported.",
                )
            )
    return findings


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argument list, no shell
        [sys.executable, "-m", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=TOOL_TIMEOUT_SECONDS,
        stdin=subprocess.DEVNULL,
    )


def _relative(filename: str, root: Path) -> str:
    path = Path(filename)
    if path.is_absolute():
        return path.resolve().relative_to(root.resolve()).as_posix()
    return PurePosixPath(filename.replace("\\", "/")).as_posix().removeprefix("./")


def _run_ruff(root: Path) -> list[Finding]:
    proc = _run(
        [
            "ruff",
            "check",
            "--isolated",
            "--no-cache",
            "--exit-zero",
            "--select",
            RUFF_SELECT,
            "--ignore",
            RUFF_IGNORE,
            "--output-format",
            "json",
            ".",
        ],  # fmt: skip
        root,
    )
    if proc.returncode != 0:
        raise ValueError(f"ruff exited with {proc.returncode}: {proc.stderr.strip()[:200]}")
    findings = []
    for item in json.loads(proc.stdout or "[]"):
        code = item.get("code") or ""
        if not RULE_CODE.fullmatch(code):
            continue  # syntax errors: already reported once by Python's own parser
        high = code in RUFF_HIGH or code.startswith("E9")
        findings.append(
            Finding(
                source="ruff",
                rule=code,
                file=_relative(item["filename"], root),
                line=(item.get("location") or {}).get("row") or 0,
                severity="high" if high else "low",
                category="bug" if high else "quality",
                message=item.get("message", ""),
                suggested_fix=((item.get("fix") or {}).get("message")) or f"See ruff rule {code}.",
            )
        )
    return findings


def _run_bandit(root: Path) -> list[Finding]:
    proc = _run(["bandit", "-r", ".", "-f", "json", "-q"], root)
    # bandit exits 1 when it found issues; anything else without JSON is a failure
    if proc.returncode not in (0, 1):
        raise ValueError(f"bandit exited with {proc.returncode}: {proc.stderr.strip()[:200]}")
    data = json.loads(proc.stdout or "{}")
    findings = []
    for item in data.get("results", []):
        findings.append(
            Finding(
                source="bandit",
                rule=item.get("test_id", ""),
                file=_relative(item["filename"], root),
                line=item.get("line_number") or 0,
                severity=BANDIT_SEVERITY.get(item.get("issue_severity", ""), "low"),
                category="security",
                message=item.get("issue_text", ""),
                suggested_fix=f"See bandit rule {item.get('test_id', '')}.",
            )
        )
    return findings
