"""Parse pytest's JUnit XML report into structured results.

The report comes out of the sandbox, so it is untrusted: it is size-limited and parsed
with defusedxml, which refuses entity tricks such as the "billion laughs" expansion.
"""

from defusedxml import ElementTree

from app.execution.base import MAX_MESSAGE_CHARS, TestCaseResult, tail

MAX_REPORT_BYTES = 2_000_000


class ReportError(ValueError):
    pass


def parse_junit(xml_text: str) -> list[TestCaseResult]:
    if len(xml_text.encode("utf-8")) > MAX_REPORT_BYTES:
        raise ReportError("test report is too large")
    try:
        root = ElementTree.fromstring(xml_text)
    except Exception as exc:  # defusedxml raises several types for hostile input
        raise ReportError(f"unreadable test report: {type(exc).__name__}") from exc

    cases = []
    for case in root.iter("testcase"):
        file = case.get("file") or _module_to_path(case.get("classname", ""))
        if file:
            name = f"{file}::{case.get('name', '?')}"
        else:
            # A module that fails to import is reported with an empty classname and the
            # dotted module as name: <testcase classname="" name="tests.test_x">
            module = _module_to_path(case.get("name", ""))
            name = f"{module}::(collection)" if module else case.get("name", "?")
        outcome, message = "passed", ""
        for child in case:
            if child.tag in ("failure", "error", "skipped"):
                outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[child.tag]
                message = (child.get("message") or "") + "\n" + (child.text or "")
                break
        cases.append(
            TestCaseResult(
                name=name,
                outcome=outcome,
                message=tail(message.strip(), MAX_MESSAGE_CHARS),
            )
        )
    return cases


def _module_to_path(classname: str) -> str:
    # pytest writes classname "tests.test_todos" (or "tests.test_todos.TestX")
    parts = [p for p in classname.split(".") if p]
    while parts and not parts[-1].startswith("test_"):
        parts.pop()
    return "/".join(parts) + ".py" if parts else ""
