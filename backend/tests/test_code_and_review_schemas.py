import pytest
from pydantic import ValidationError

from app.schemas.code import CodeChanges
from app.schemas.review import Finding, ReviewOutput, ReviewReport
from tests.conftest import code_changes, finding


def test_code_changes_accepts_valid_files(todo_files):
    changes = CodeChanges.model_validate(code_changes(todo_files))
    assert changes.as_dict() == todo_files


@pytest.mark.parametrize(
    "files",
    [
        {"../evil.py": "x = 1\n"},
        {"tests/test_main.py": "def test(): pass\n"},
        {"app/main.py": "   \n"},
        {"run.sh": "rm -rf /\n"},
    ],
)
def test_code_changes_rejects_bad_files(files):
    with pytest.raises(ValidationError):
        CodeChanges.model_validate(code_changes(files))


def test_empty_package_marker_is_allowed():
    # Found in a live run: the model correctly returned an empty app/__init__.py
    changes = CodeChanges.model_validate(code_changes({"app/__init__.py": ""}))
    assert changes.as_dict() == {"app/__init__.py": ""}


def test_code_changes_rejects_duplicates_and_empty():
    data = code_changes({"a.py": "x = 1\n"})
    data["files"].append(dict(data["files"][0]))
    with pytest.raises(ValidationError, match="once"):
        CodeChanges.model_validate(data)
    # An empty answer is valid JSON; the agent's own check decides if it is acceptable.
    assert CodeChanges.model_validate({"files": [], "notes": ""}).files == []


def make_report(*severities: str) -> ReviewReport:
    findings = [Finding(source="reviewer", **finding(severity=s)) for s in severities]
    return ReviewReport(round=1, summary="", findings=findings)


def test_verdict_is_computed_from_findings_not_chosen_by_the_model():
    assert make_report().verdict == "pass"
    assert make_report("medium", "low").verdict == "pass"
    assert make_report("low", "high").verdict == "changes_needed"


def test_revision_fixes_high_and_medium_only():
    report = make_report("high", "medium", "low")
    assert [f.severity for f in report.to_fix] == ["high", "medium"]
    assert report.counts() == {"high": 1, "medium": 1, "low": 1}


def test_negative_line_numbers_become_zero():
    output = ReviewOutput.model_validate({"summary": "", "findings": [finding(line=-5)]})
    assert output.findings[0].line == 0


def test_unknown_severity_is_rejected():
    with pytest.raises(ValidationError):
        ReviewOutput.model_validate({"summary": "", "findings": [finding(severity="critical")]})
