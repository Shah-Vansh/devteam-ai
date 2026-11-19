"""Approval tokens, git safety rules, and the Git MCP server."""

import base64
import json
import os
import shutil
import subprocess
import sys

import pytest

from app.gitops.approval import (
    TokenError,
    content_digest,
    issue_token,
    new_secret,
    verify_token,
)
from app.gitops.repo import GitError, GitRepos, validate_message
from app.mcp_clients.base import BACKEND_DIR
from app.mcp_clients.git import GitClient, GitToolError, files_digest
from app.mcp_servers.git.server import build_git_server
from app.workspace.store import WorkspaceFiles

GIT = shutil.which("git") or "git"
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
WS = "demo"
FILES = {"app/main.py": b"print(1)\n", "requirements.txt": b"fastapi\n"}

# ---------- tokens ----------


def check(secret, token, *, workspace=WS, digest=None, used=None, now=None):
    return verify_token(
        secret,
        token,
        workspace=workspace,
        digest=digest or content_digest(FILES),
        used_nonces=used if used is not None else set(),
        now=now,
    )


def code_of(call) -> str:
    with pytest.raises((TokenError, GitError, GitToolError)) as info:
        call()
    return info.value.code


def test_valid_token_is_accepted_once():
    secret, used = new_secret(), set()
    token = issue_token(secret, WS, content_digest(FILES))
    assert check(secret, token, used=used)["workspace"] == WS
    assert code_of(lambda: check(secret, token, used=used)) == "TOKEN_USED"


def test_token_signed_with_another_secret_is_invalid():
    token = issue_token(new_secret(), WS, content_digest(FILES))
    assert code_of(lambda: check(new_secret(), token)) == "TOKEN_INVALID"


def test_editing_the_payload_breaks_the_signature():
    secret = new_secret()
    token = issue_token(secret, "other-ws", content_digest(FILES))
    body, signature = token.split(".")
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["workspace"] = WS  # try to reuse a token for another workspace
    forged = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    assert code_of(lambda: check(secret, f"{forged}.{signature}")) == "TOKEN_INVALID"


@pytest.mark.parametrize("token", ["", "abc", "abc.", ".sig", "not-base64!.00"])
def test_missing_or_malformed_tokens(token):
    assert code_of(lambda: check(new_secret(), token)) in ("TOKEN_MISSING", "TOKEN_INVALID")


def test_expired_token():
    secret = new_secret()
    token = issue_token(secret, WS, content_digest(FILES), ttl=60, now=1000)
    assert code_of(lambda: check(secret, token, now=1061)) == "TOKEN_EXPIRED"


def test_token_for_another_workspace():
    secret = new_secret()
    token = issue_token(secret, "other", content_digest(FILES))
    assert code_of(lambda: check(secret, token)) == "TOKEN_WRONG_WORKSPACE"


def test_changed_content_after_approval():
    secret = new_secret()
    token = issue_token(secret, WS, content_digest(FILES))
    changed = content_digest({**FILES, "app/main.py": b"import os\n"})
    assert code_of(lambda: check(secret, token, digest=changed)) == "CONTENT_CHANGED"


def test_digest_depends_on_paths_and_bytes_not_order():
    assert content_digest(FILES) == content_digest(dict(reversed(FILES.items())))
    assert content_digest(FILES) != content_digest({**FILES, "extra.py": b""})
    assert content_digest(FILES) != content_digest({"app/main2.py": b"print(1)\n"})
    assert content_digest({"a.py": b"x\r\n"}) != content_digest({"a.py": b"x\n"})
    as_text = {p: c.decode() for p, c in FILES.items()}
    assert files_digest(as_text) == content_digest(FILES)


@pytest.mark.parametrize(
    "message",
    ["", "   ", "x" * 101, "subject\x00", "subject\x1b[31m", "y" * 2001],
)
def test_bad_commit_messages(message):
    assert code_of(lambda: validate_message(message)) == "INVALID_MESSAGE"


def test_good_commit_message_is_normalised():
    assert validate_message("  Add todo-api\n\nBody line\n\n") == "Add todo-api\n\nBody line\n"


# ---------- repositories ----------


def git(*args, cwd):
    return subprocess.run(  # noqa: S603
        [GIT, *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def repos(tmp_path):
    store = WorkspaceFiles(tmp_path / "workspaces")
    for path, content in FILES.items():
        store.create_file(WS, path, content.decode())
    secret = new_secret()
    return GitRepos(store, commit_secret=secret), store, secret


def token_for(store, secret, workspace=WS):
    return issue_token(secret, workspace, content_digest(store.snapshot(workspace)))


@needs_git
def test_workspace_inside_another_repository_is_never_confused_with_it(tmp_path):
    # Like this project: workspaces/ lives inside the checkout of an outer repository.
    outer = tmp_path / "outer"
    outer.mkdir()
    git("init", "-q", cwd=outer)
    (outer / "outer.txt").write_text("outer file")
    store = WorkspaceFiles(outer / "workspaces")
    store.create_file(WS, "app/main.py", "x = 1\n")
    repos = GitRepos(store, commit_secret=new_secret())

    assert code_of(lambda: repos.get_git_status(WS)) == "NOT_A_REPOSITORY"
    assert code_of(lambda: repos.get_commit_history(WS)) == "NOT_A_REPOSITORY"
    repos.initialize_repository(WS)
    status = repos.get_git_status(WS)
    assert [f["path"] for f in status["files"]] == ["app/main.py"]  # not outer.txt


@needs_git
def test_commit_requires_a_token_and_uses_it_once(repos):
    git_repos, store, secret = repos
    git_repos.initialize_repository(WS)
    assert code_of(lambda: git_repos.create_commit(WS, "Add demo", "")) == "TOKEN_MISSING"
    token = token_for(store, secret)
    result = git_repos.create_commit(WS, "Add demo", token)
    assert sorted(result["files"]) == sorted(FILES)
    assert code_of(lambda: git_repos.create_commit(WS, "Again", token)) == "TOKEN_USED"
    history = git_repos.get_commit_history(WS)["commits"]
    assert [c["subject"] for c in history] == ["Add demo"]


@needs_git
def test_nothing_to_commit(repos):
    git_repos, store, secret = repos
    git_repos.initialize_repository(WS)
    git_repos.create_commit(WS, "Add demo", token_for(store, secret))
    assert (
        code_of(lambda: git_repos.create_commit(WS, "Empty", token_for(store, secret)))
        == "NOTHING_TO_COMMIT"
    )


@needs_git
def test_initialize_is_idempotent(repos):
    git_repos, _, _ = repos
    assert git_repos.initialize_repository(WS) == {"created": True, "branch": "main"}
    assert git_repos.initialize_repository(WS) == {"created": False, "branch": "main"}


@needs_git
def test_line_endings_are_stored_exactly(repos, tmp_path):
    git_repos, store, secret = repos
    store.update_file(WS, "app/main.py", "print(1)\r\n")
    git_repos.initialize_repository(WS)
    git_repos.create_commit(WS, "Add demo", token_for(store, secret))
    ws = store.workspace_path(WS)
    blob = subprocess.run(  # noqa: S603
        [GIT, f"--git-dir={ws / '.git'}", "show", "HEAD:app/main.py"],
        capture_output=True,
        check=True,
    ).stdout
    assert blob == b"print(1)\r\n"


@needs_git
def test_user_git_config_and_hooks_are_ignored(repos, tmp_path, monkeypatch):
    git_repos, store, secret = repos
    # A global config that would break or slow commits (signing, a template with hooks).
    config = tmp_path / "evil.gitconfig"
    config.write_text("[commit]\n\tgpgSign = true\n[user]\n\tname = Someone Else\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    git_repos.initialize_repository(WS)
    hooks = store.workspace_path(WS) / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 1\n")
    result = git_repos.create_commit(WS, "Add demo", token_for(store, secret))
    assert result["commit"]
    assert git_repos.get_commit_history(WS)["commits"][0]["author"] == "DevTeam AI"


@needs_git
def test_history_limit_is_bounded(repos):
    git_repos, _, _ = repos
    git_repos.initialize_repository(WS)
    assert git_repos.get_commit_history(WS)["commits"] == []
    assert code_of(lambda: git_repos.get_commit_history(WS, 51)) == "INVALID_LIMIT"


def test_invalid_workspace_names_are_refused(repos):
    git_repos, _, _ = repos
    assert code_of(lambda: git_repos.initialize_repository("../x")) == "INVALID_WORKSPACE"
    assert code_of(lambda: git_repos.get_git_status("missing")) == "WORKSPACE_NOT_FOUND"


# ---------- MCP server and client ----------


@pytest.fixture
def anyio_backend():
    return "asyncio"


@needs_git
@pytest.mark.anyio
async def test_git_server_tools_and_refusals(tmp_path):
    store = WorkspaceFiles(tmp_path / "workspaces")
    store.create_file(WS, "app/main.py", "x = 1\n")
    secret = new_secret()
    server = build_git_server(tmp_path / "workspaces", commit_secret=secret)
    async with GitClient(server, secret=secret) as client:
        tools = {t.name: t for t in await client.list_tools()}
        assert set(tools) == {
            "initialize_repository", "get_git_status", "create_commit", "get_commit_history",
        }  # fmt: skip
        assert tools["get_git_status"].annotations.read_only_hint is True
        assert "approval_token" in tools["create_commit"].input_schema["required"]

        await client.initialize_repository(WS)
        with pytest.raises(GitToolError) as info:
            await client.create_commit(WS, "Add demo", "forged.token")
        assert info.value.code == "TOKEN_INVALID"

        token = client.issue_commit_token(WS, files_digest({"app/main.py": "x = 1\n"}))
        result = await client.create_commit(WS, "Add demo", token)
        assert (await client.get_commit_history(WS))[0]["commit"] == result["commit"]


@needs_git
@pytest.mark.anyio
async def test_git_server_over_stdio_with_its_own_secret(tmp_path):
    store = WorkspaceFiles(tmp_path / "workspaces")
    store.create_file(WS, "app/main.py", "x = 1\n")
    async with GitClient.over_stdio(tmp_path / "workspaces") as client:
        await client.initialize_repository(WS)
        token = client.issue_commit_token(WS, files_digest({"app/main.py": "x = 1\n"}))
        result = await client.create_commit(WS, "Add demo", token)
        assert len(result["commit"]) == 40
        # A token signed by anyone else (another secret) is refused by this server.
        stranger = issue_token(new_secret(), WS, files_digest({"app/main.py": "x = 1\n"}))
        with pytest.raises(GitToolError) as info:
            await client.create_commit(WS, "Again", stranger)
        assert info.value.code == "TOKEN_INVALID"


def test_git_server_refuses_to_start_without_a_secret(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("DEVTEAM_")}
    env["DEVTEAM_WORKSPACES_DIR"] = str(tmp_path)
    proc = subprocess.run(  # noqa: S603 - fixed arguments, our own module
        [sys.executable, "-m", "app.mcp_servers.git"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 2
    assert "DEVTEAM_COMMIT_SECRET" in proc.stderr
