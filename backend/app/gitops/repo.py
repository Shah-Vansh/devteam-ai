"""Git operations on a workspace, with the safety rules in one place.

- `git` runs with a fixed argument list, never through a shell; the only values that come
  from callers are the workspace name (validated) and the commit message (validated, passed
  as one argument after `-m`).
- Every command names the repository explicitly (`--git-dir`, `--work-tree`). Workspaces live
  inside this project's own checkout, so letting git search upward for a `.git` folder would
  silently operate on the outer repository. That is refused instead.
- The user's own git configuration is ignored (no system or global config): no signing
  prompts, no aliases, no hooks path, no credential helpers. Hooks are disabled explicitly.
- Line endings are stored exactly as written (`core.autocrlf=false`).
- No remotes, no push, no network.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.gitops.approval import TokenError, content_digest, verify_token
from app.workspace.store import WorkspaceError, WorkspaceFiles

GIT_TIMEOUT_SECONDS = 30
MAX_MESSAGE_CHARS = 2000
MAX_SUBJECT_CHARS = 100
MAX_HISTORY = 50
DEFAULT_AUTHOR = ("DevTeam AI", "devteam-ai@localhost")

SAFE_CONFIG = [
    "-c", f"core.hooksPath={os.devnull}",
    "-c", "core.autocrlf=false",
    "-c", "core.fsmonitor=false",
    "-c", "commit.gpgSign=false",
    "-c", "init.defaultBranch=main",
]  # fmt: skip


class GitError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class CommitAuthor:
    name: str = DEFAULT_AUTHOR[0]
    email: str = DEFAULT_AUTHOR[1]


def validate_message(message: str) -> str:
    if not isinstance(message, str) or not message.strip():
        raise GitError("INVALID_MESSAGE", "commit message is empty")
    if len(message) > MAX_MESSAGE_CHARS:
        raise GitError("INVALID_MESSAGE", f"commit message longer than {MAX_MESSAGE_CHARS}")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in message):
        raise GitError("INVALID_MESSAGE", "commit message contains control characters")
    if len(message.splitlines()[0]) > MAX_SUBJECT_CHARS:
        raise GitError("INVALID_MESSAGE", f"first line longer than {MAX_SUBJECT_CHARS}")
    return message.strip() + "\n"


class GitRepos:
    def __init__(
        self,
        store: WorkspaceFiles,
        *,
        commit_secret: str,
        author: CommitAuthor | None = None,
        git: str | None = None,
    ) -> None:
        self.store = store
        self._secret = commit_secret
        self._author = author or CommitAuthor()
        self._git = git or shutil.which("git")
        self._used_nonces: set[str] = set()  # one-time tokens already spent

    # ---------- tools ----------

    def initialize_repository(self, workspace: str) -> dict:
        ws = self._workspace(workspace)
        if (ws / ".git").exists():
            return {"created": False, "branch": self._branch(ws)}
        self._run(ws, ["init", "-q", "-b", "main", str(ws)], repo=False)
        return {"created": True, "branch": "main"}

    def get_git_status(self, workspace: str) -> dict:
        ws = self._repo(workspace)
        out = self._run(ws, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
        files = []
        for entry in filter(None, out.split("\0")):
            files.append({"status": entry[:2].strip() or "?", "path": entry[3:]})
        return {"branch": self._branch(ws), "clean": not files, "files": files}

    def create_commit(self, workspace: str, message: str, approval_token: str) -> dict:
        ws = self._repo(workspace)
        text = validate_message(message)
        # The token must match the workspace and the exact bytes on disk right now.
        digest = content_digest(self.store.snapshot(workspace))
        try:
            verify_token(
                self._secret,
                approval_token,
                workspace=workspace,
                digest=digest,
                used_nonces=self._used_nonces,
            )
        except TokenError as exc:
            raise GitError(exc.code, exc.message) from None

        self._run(ws, ["add", "-A"])
        staged = self._run(ws, ["diff", "--cached", "--name-only", "-z"])
        if not staged.strip("\0"):
            raise GitError("NOTHING_TO_COMMIT", "no changes to commit")
        author = ["-c", f"user.name={self._author.name}", "-c", f"user.email={self._author.email}"]
        self._run(ws, [*author, "commit", "-q", "-m", text])
        commit = self._run(ws, ["rev-parse", "HEAD"]).strip()
        return {
            "commit": commit,
            "branch": self._branch(ws),
            "files": [p for p in staged.split("\0") if p],
        }

    def get_commit_history(self, workspace: str, limit: int = 10) -> dict:
        ws = self._repo(workspace)
        if not 1 <= limit <= MAX_HISTORY:
            raise GitError("INVALID_LIMIT", f"limit must be between 1 and {MAX_HISTORY}")
        try:
            out = self._run(ws, ["log", f"-n{limit}", "--format=%H%x1f%an%x1f%aI%x1f%s"])
        except GitError as exc:
            if "does not have any commits" in exc.message:
                return {"commits": []}
            raise
        commits = []
        for line in filter(None, out.splitlines()):
            sha, author, date, subject = line.split("\x1f", 3)
            commits.append({"commit": sha, "author": author, "date": date, "subject": subject})
        return {"commits": commits}

    # ---------- helpers ----------

    def _workspace(self, workspace: str) -> Path:
        try:
            return self.store.workspace_path(workspace)
        except WorkspaceError as exc:
            raise GitError(exc.code, exc.message) from None

    def _repo(self, workspace: str) -> Path:
        ws = self._workspace(workspace)
        if not (ws / ".git").is_dir():
            raise GitError("NOT_A_REPOSITORY", f"workspace {workspace!r} has no repository yet")
        return ws

    def _branch(self, ws: Path) -> str:
        return self._run(ws, ["symbolic-ref", "--short", "HEAD"]).strip()

    def _run(self, ws: Path, args: list[str], *, repo: bool = True) -> str:
        if not self._git:
            raise GitError("GIT_NOT_FOUND", "git is not installed")
        where = [f"--git-dir={ws / '.git'}", f"--work-tree={ws}"] if repo else []
        env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CEILING_DIRECTORIES": str(ws.parent),  # never search above the workspace
        }
        proc = subprocess.run(  # noqa: S603 - fixed argument list, no shell
            [self._git, *SAFE_CONFIG, *where, *args],
            cwd=ws,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=GIT_TIMEOUT_SECONDS,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            # stderr only; it names files relative to the repository
            detail = proc.stderr.strip().splitlines()
            raise GitError("GIT_FAILED", (detail[-1] if detail else "git failed")[:300])
        return proc.stdout
