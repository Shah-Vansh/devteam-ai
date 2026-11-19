"""Which packages a generated project may install in the sandbox, and at which versions.

Package installation is the one moment the sandbox has internet access, so it is kept
narrow: only names on this allow-list, and every package (including dependencies of
dependencies) pinned by `constraints.txt`. The constraints file is generated inside an
E2B sandbox by `scripts/lock_sandbox_packages.py`, so it matches the sandbox's Python.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

CONSTRAINTS_FILE = Path(__file__).parent / "constraints.txt"

# requirement name -> what to install (extras included)
ALLOWED_PACKAGES: dict[str, str] = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "pydantic-settings": "pydantic-settings",
    "email-validator": "email-validator",
    "python-multipart": "python-multipart",
    "sqlalchemy": "sqlalchemy",
    "pyjwt": "pyjwt",
    "python-jose": "python-jose[cryptography]",
    "passlib": "passlib[bcrypt]",
    "bcrypt": "bcrypt",
    "httpx": "httpx",
}
# Always installed: the test runner and what FastAPI's TestClient needs.
TEST_PACKAGES = ("pytest", "httpx")

# import name -> requirement name, for checking that requirements.txt declares what the
# code imports (import names and package names often differ: `jose` is python-jose).
IMPORT_TO_PACKAGE: dict[str, str] = {
    "fastapi": "fastapi",
    "starlette": "fastapi",  # installed with fastapi
    "uvicorn": "uvicorn",
    "pydantic": "pydantic",
    "pydantic_settings": "pydantic-settings",
    "email_validator": "email-validator",
    "multipart": "python-multipart",
    "python_multipart": "python-multipart",
    "sqlalchemy": "sqlalchemy",
    "jwt": "pyjwt",
    "jose": "python-jose",
    "passlib": "passlib",
    "bcrypt": "bcrypt",
    "httpx": "httpx",
}
# Packages that bring another allowed package with them.
IMPLIED = {"fastapi": {"pydantic"}, "passlib": {"bcrypt"}, "pydantic-settings": {"pydantic"}}


def declared_packages(requirements_text: str) -> set[str]:
    names = set()
    for raw in requirements_text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if match := _NAME.match(line):
            name = normalize(match.group(1))
            names |= {name, *IMPLIED.get(name, set())}
    return names


# Versions that must not float, with the reason. Applied when generating constraints.
OVERRIDES = {
    # passlib 1.7.4 (latest) breaks with bcrypt >= 4.1: its self-test raises ValueError.
    "bcrypt": "4.0.1",
}

_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass
class PackageSelection:
    install: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


def select_packages(requirements_text: str) -> PackageSelection:
    """Turn a generated requirements.txt into an install list. Version specifiers are
    ignored (the constraints file decides versions); unknown names are rejected."""
    selection = PackageSelection()
    for raw in requirements_text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            # options such as `-r other.txt` or `--index-url` are never honoured
            if line:
                selection.rejected.append(line)
            continue
        match = _NAME.match(line)
        if not match:
            selection.rejected.append(line)
            continue
        name = normalize(match.group(1))
        if name in ALLOWED_PACKAGES:
            spec = ALLOWED_PACKAGES[name]
            if spec not in selection.install:
                selection.install.append(spec)
        else:
            selection.rejected.append(line)
    for spec in TEST_PACKAGES:
        if spec not in selection.install:
            selection.install.append(spec)
    return selection


def allowed_names_text() -> str:
    return ", ".join(sorted(ALLOWED_PACKAGES))


def packages_rule() -> str:
    """Appended to the Planner and Developer prompts, generated from the same allow-list
    the executor enforces, so the prompt and the sandbox cannot disagree."""
    return (
        "\nPackages: the project may depend only on these pip packages: "
        f"{allowed_names_text()}. Use nothing else (no other database drivers, no "
        "external services).\n"
    )
