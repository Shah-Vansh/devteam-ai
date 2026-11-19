"""Rules for paths that come from untrusted sources (LLM output, API input).

These are *syntax* checks, done on the string before touching the disk. They are
deliberately stricter than any operating system, so a path accepted here means the
same file on Windows, Linux and macOS:

- relative, forward slashes only, no drive letters, UNC paths or `:` streams
- no `.` / `..` segments, no empty segments, no hidden (dot) files or folders
- no Windows reserved device names (`CON`, `NUL`, `COM1` ...), in any case, with
  or without an extension
- no characters Windows forbids, no control characters or null bytes
- an allowed file extension

The *containment* check (does the resolved real path stay inside the workspace,
after following symlinks?) needs the disk and lives in `store.py`.
"""

import re
from pathlib import PurePosixPath

ALLOWED_EXTENSIONS = frozenset(
    {".py", ".txt", ".md", ".toml", ".ini", ".cfg", ".json", ".yaml", ".yml"}
)
MAX_PATH_LENGTH = 200
MAX_PATH_DEPTH = 8

_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"{dev}{n}" for dev in ("COM", "LPT") for n in [*"0123456789", "¹", "²", "³"]}
)
_FORBIDDEN_CHARS = set('<>:"|?*\\')
_WORKSPACE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


class PathRejected(ValueError):
    """A path or name broke a rule. `code` is stable and machine-readable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _is_reserved(segment: str) -> bool:
    # Windows ignores everything from the first dot and trailing spaces:
    # "nul.txt" and "NUL .py" both open the null device.
    stem = segment.split(".", 1)[0].rstrip(" ")
    return stem.upper() in _RESERVED_NAMES


def _check_segment(segment: str, path: str) -> None:
    if segment in ("", ".", ".."):
        raise PathRejected("INVALID_PATH", f"empty, '.' or '..' segment in {path!r}")
    if segment.startswith("."):
        raise PathRejected("INVALID_PATH", f"hidden files and folders are not allowed: {path!r}")
    if segment[-1] in ". ":
        raise PathRejected("INVALID_PATH", f"segment ends with '.' or space: {path!r}")
    if any(ch in _FORBIDDEN_CHARS or ord(ch) < 32 for ch in segment):
        raise PathRejected("INVALID_PATH", f"forbidden character in {path!r}")
    if _is_reserved(segment):
        raise PathRejected("INVALID_PATH", f"reserved Windows device name in {path!r}")


def validate_relative_path(path: str) -> str:
    """Return `path` unchanged if it is a safe relative file path, else raise PathRejected."""
    if not isinstance(path, str) or not path:
        raise PathRejected("INVALID_PATH", "path must be a non-empty string")
    if len(path) > MAX_PATH_LENGTH:
        raise PathRejected("INVALID_PATH", f"path longer than {MAX_PATH_LENGTH} characters")
    if "\x00" in path:
        raise PathRejected("INVALID_PATH", "path contains a null byte")
    if "\\" in path or ":" in path or path.startswith("/"):
        # Backslashes, drive letters (C:), UNC (\\server) and NTFS streams (a.py:x)
        raise PathRejected("INVALID_PATH", f"path must be relative and use '/': {path!r}")

    segments = path.split("/")
    if len(segments) > MAX_PATH_DEPTH:
        raise PathRejected("INVALID_PATH", f"path deeper than {MAX_PATH_DEPTH} levels: {path!r}")
    for segment in segments:
        _check_segment(segment, path)

    if PurePosixPath(path).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise PathRejected("EXTENSION_NOT_ALLOWED", f"file type not allowed: {path!r}")
    return path


def validate_workspace_name(name: str) -> str:
    """Workspace folder names: lowercase letters, digits, '-' and '_', at most 64 characters."""
    if not isinstance(name, str) or not _WORKSPACE_NAME.fullmatch(name) or _is_reserved(name):
        raise PathRejected("INVALID_WORKSPACE", f"invalid workspace name: {name!r}")
    return name
