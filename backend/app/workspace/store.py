"""File operations inside project workspaces.

Layout: `<workspaces_root>/<workspace>/<relative path>`.

Every operation:
1. checks the workspace name and the relative path as strings (`paths.py`);
2. resolves the real path on disk, following symlinks and junctions, and refuses
   anything that ends up outside the workspace folder (`PATH_ESCAPE`);
3. enforces size and count limits;
4. reports errors with a stable code and a message that never contains absolute
   host paths, because messages can reach the LLM.

This module knows nothing about MCP; the Filesystem MCP server is a thin wrapper.
"""

import os
import tempfile
from pathlib import Path

from app.workspace.paths import PathRejected, validate_relative_path, validate_workspace_name

DEFAULT_MAX_FILE_BYTES = 100_000
DEFAULT_MAX_FILES = 50

ERROR_CODES = (
    "INVALID_PATH",
    "INVALID_WORKSPACE",
    "EXTENSION_NOT_ALLOWED",
    "PATH_ESCAPE",
    "WORKSPACE_NOT_FOUND",
    "FILE_EXISTS",
    "FILE_NOT_FOUND",
    "NOT_A_FILE",
    "NOT_TEXT",
    "FILE_TOO_LARGE",
    "WORKSPACE_FULL",
    "INVALID_CONTENT",
    "IO_ERROR",
)


class WorkspaceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WorkspaceFiles:
    def __init__(
        self,
        root: Path,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_files: int = DEFAULT_MAX_FILES,
    ) -> None:
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()
        self.max_file_bytes = max_file_bytes
        self.max_files = max_files

    # ---------- public operations ----------

    def create_file(self, workspace: str, path: str, content: str) -> dict:
        data = self._encode(path, content)
        ws = self._workspace_dir(workspace, create=True)
        target = self._resolve(ws, path)
        if target.is_dir():
            # Checked first: Windows reports opening a folder as "permission denied"
            raise WorkspaceError("NOT_A_FILE", f"a folder exists at {path!r}")
        if self._count_files(ws) >= self.max_files:
            raise WorkspaceError("WORKSPACE_FULL", f"workspace already has {self.max_files} files")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            # "x" = create only; fails instead of silently overwriting
            with open(target, "xb") as fh:
                fh.write(data)
        except FileExistsError:
            raise WorkspaceError("FILE_EXISTS", f"file already exists: {path!r}") from None
        except OSError as exc:
            raise self._io_error("create", path, exc) from None
        return {"path": path, "size_bytes": len(data)}

    def read_file(self, workspace: str, path: str) -> dict:
        ws = self._workspace_dir(workspace)
        target = self._existing_file(ws, path)
        size = target.stat().st_size
        if size > self.max_file_bytes:
            raise WorkspaceError("FILE_TOO_LARGE", f"{path!r} is {size} bytes")
        try:
            content = target.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise WorkspaceError("NOT_TEXT", f"{path!r} is not UTF-8 text") from None
        except OSError as exc:
            raise self._io_error("read", path, exc) from None
        return {"path": path, "content": content, "size_bytes": size}

    def update_file(self, workspace: str, path: str, content: str) -> dict:
        data = self._encode(path, content)
        ws = self._workspace_dir(workspace)
        target = self._existing_file(ws, path)
        try:
            # Write a temporary file next to the target, then swap it in, so a crash
            # never leaves a half-written file behind.
            fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                os.replace(tmp_name, target)
            except BaseException:
                Path(tmp_name).unlink(missing_ok=True)
                raise
        except OSError as exc:
            raise self._io_error("update", path, exc) from None
        return {"path": path, "size_bytes": len(data)}

    def list_files(self, workspace: str) -> dict:
        ws = self._workspace_dir(workspace)
        files = [{"path": rel, "size_bytes": (ws / rel).stat().st_size} for rel in self._walk(ws)]
        return {"files": files}

    # ---------- helpers ----------

    def _encode(self, path: str, content: str) -> bytes:
        validate_or_raise(path)
        if not isinstance(content, str):
            raise WorkspaceError("INVALID_CONTENT", "content must be a string")
        data = content.encode("utf-8")
        if len(data) > self.max_file_bytes:
            raise WorkspaceError(
                "FILE_TOO_LARGE", f"{len(data)} bytes; limit is {self.max_file_bytes}"
            )
        return data

    def _workspace_dir(self, workspace: str, *, create: bool = False) -> Path:
        try:
            validate_workspace_name(workspace)
        except PathRejected as exc:
            raise WorkspaceError(exc.code, str(exc)) from None
        candidate = self.root / workspace
        if create:
            candidate.mkdir(exist_ok=True)
        if not candidate.is_dir():
            raise WorkspaceError("WORKSPACE_NOT_FOUND", f"workspace {workspace!r} does not exist")
        # A workspace folder that is itself a symlink or junction would point elsewhere.
        if candidate.resolve() != candidate:
            raise WorkspaceError("PATH_ESCAPE", f"workspace {workspace!r} is a link")
        return candidate

    def _resolve(self, ws: Path, path: str) -> Path:
        validate_or_raise(path)
        resolved = ws.joinpath(*path.split("/")).resolve()
        if not resolved.is_relative_to(ws):
            raise WorkspaceError("PATH_ESCAPE", f"{path!r} resolves outside the workspace")
        return resolved

    def _existing_file(self, ws: Path, path: str) -> Path:
        target = self._resolve(ws, path)
        if not target.exists():
            raise WorkspaceError("FILE_NOT_FOUND", f"no such file: {path!r}")
        if not target.is_file():
            raise WorkspaceError("NOT_A_FILE", f"{path!r} is not a file")
        return target

    def _walk(self, ws: Path) -> list[str]:
        """Relative paths of regular files, skipping hidden entries and links."""
        result: list[str] = []
        for dirpath, dirnames, filenames in os.walk(ws, followlinks=False):
            here = Path(dirpath)
            dirnames[:] = sorted(
                d for d in dirnames if not d.startswith(".") and not _is_link(here / d)
            )
            for name in sorted(filenames):
                full = here / name
                if name.startswith(".") or _is_link(full):
                    continue
                result.append(full.relative_to(ws).as_posix())
        return sorted(result)

    def _count_files(self, ws: Path) -> int:
        return len(self._walk(ws))

    @staticmethod
    def _io_error(action: str, path: str, exc: OSError) -> WorkspaceError:
        # exc.strerror only, never str(exc), which includes the absolute host path
        return WorkspaceError("IO_ERROR", f"could not {action} {path!r}: {exc.strerror}")


def validate_or_raise(path: str) -> None:
    try:
        validate_relative_path(path)
    except PathRejected as exc:
        raise WorkspaceError(exc.code, str(exc)) from None


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()
