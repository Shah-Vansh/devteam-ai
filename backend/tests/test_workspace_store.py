import os
import sys

import pytest

from app.workspace.store import WorkspaceError, WorkspaceFiles

WS = "demo"


@pytest.fixture
def store(tmp_path):
    return WorkspaceFiles(tmp_path / "workspaces", max_file_bytes=1000, max_files=5)


def error_code(call) -> str:
    with pytest.raises(WorkspaceError) as info:
        call()
    return info.value.code


def make_dir_link(link, target):
    """Directory symlink, or a junction on Windows when symlinks need admin rights."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            pytest.skip("cannot create directory links here")
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


def test_root_is_created(tmp_path):
    root = tmp_path / "a" / "b"
    WorkspaceFiles(root)
    assert root.is_dir()


def test_create_then_read_round_trip_keeps_bytes_exact(store):
    content = "line one\r\nline two\nunicode: é✓\n"
    result = store.create_file(WS, "app/main.py", content)
    assert result == {"path": "app/main.py", "size_bytes": len(content.encode())}
    read = store.read_file(WS, "app/main.py")
    assert read["content"] == content  # no newline translation


def test_create_does_not_overwrite(store):
    store.create_file(WS, "a.py", "original")
    assert error_code(lambda: store.create_file(WS, "a.py", "new")) == "FILE_EXISTS"
    assert store.read_file(WS, "a.py")["content"] == "original"


def test_update_replaces_content_and_leaves_no_temp_files(store):
    store.create_file(WS, "app/a.py", "v1")
    store.update_file(WS, "app/a.py", "v2")
    assert store.read_file(WS, "app/a.py")["content"] == "v2"
    folder = store.root / WS / "app"
    assert sorted(p.name for p in folder.iterdir()) == ["a.py"]


def test_update_missing_file(store):
    store.create_file(WS, "a.py", "x")
    assert error_code(lambda: store.update_file(WS, "b.py", "x")) == "FILE_NOT_FOUND"


def test_missing_workspace(store):
    assert error_code(lambda: store.read_file("nope", "a.py")) == "WORKSPACE_NOT_FOUND"
    assert error_code(lambda: store.list_files("nope")) == "WORKSPACE_NOT_FOUND"


def test_invalid_workspace_name(store):
    assert error_code(lambda: store.create_file("../x", "a.py", "x")) == "INVALID_WORKSPACE"


def test_invalid_paths_are_rejected_before_touching_disk(store):
    assert error_code(lambda: store.create_file(WS, "../escape.py", "x")) == "INVALID_PATH"
    assert error_code(lambda: store.create_file(WS, "evil.exe", "x")) == "EXTENSION_NOT_ALLOWED"
    assert not (store.root.parent / "escape.py").exists()


def test_file_size_limit(store):
    assert error_code(lambda: store.create_file(WS, "big.py", "x" * 1001)) == "FILE_TOO_LARGE"
    store.create_file(WS, "ok.py", "x" * 1000)
    assert error_code(lambda: store.update_file(WS, "ok.py", "x" * 1001)) == "FILE_TOO_LARGE"


def test_size_limit_counts_utf8_bytes_not_characters(store):
    # 400 characters, 1200 bytes
    assert error_code(lambda: store.create_file(WS, "u.py", "€" * 400)) == "FILE_TOO_LARGE"


def test_file_count_limit(store):
    for i in range(5):
        store.create_file(WS, f"f{i}.py", "x")
    assert error_code(lambda: store.create_file(WS, "f5.py", "x")) == "WORKSPACE_FULL"


def test_content_must_be_text(store):
    assert error_code(lambda: store.create_file(WS, "a.py", b"bytes")) == "INVALID_CONTENT"


def test_read_non_utf8_file(store):
    store.create_file(WS, "a.txt", "x")
    (store.root / WS / "a.txt").write_bytes(b"\xff\xfe\x00")
    assert error_code(lambda: store.read_file(WS, "a.txt")) == "NOT_TEXT"


def test_folder_where_a_file_is_expected(store):
    store.create_file(WS, "a.py", "x")
    (store.root / WS / "pkg.py").mkdir()
    assert error_code(lambda: store.read_file(WS, "pkg.py")) == "NOT_A_FILE"
    assert error_code(lambda: store.create_file(WS, "pkg.py", "x")) == "NOT_A_FILE"


def test_list_files_is_sorted_and_skips_hidden_entries(store):
    store.create_file(WS, "app/main.py", "x")
    store.create_file(WS, "requirements.txt", "fastapi\n")
    store.create_file(WS, "app/models/user.py", "yy")
    git = store.root / WS / ".git"
    git.mkdir()
    (git / "config").write_text("secret")
    files = store.list_files(WS)["files"]
    assert [f["path"] for f in files] == ["app/main.py", "app/models/user.py", "requirements.txt"]
    assert files[1]["size_bytes"] == 2


def test_link_inside_workspace_cannot_escape(store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("top secret")
    store.create_file(WS, "a.py", "x")
    make_dir_link(store.root / WS / "link", outside)

    assert error_code(lambda: store.read_file(WS, "link/secret.txt")) == "PATH_ESCAPE"
    assert error_code(lambda: store.create_file(WS, "link/new.py", "x")) == "PATH_ESCAPE"
    assert error_code(lambda: store.update_file(WS, "link/secret.txt", "x")) == "PATH_ESCAPE"
    assert sorted(p.name for p in outside.iterdir()) == ["secret.txt"]
    assert (outside / "secret.txt").read_text() == "top secret"
    assert [f["path"] for f in store.list_files(WS)["files"]] == ["a.py"]


def test_workspace_that_is_a_link_is_refused(store, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    make_dir_link(store.root / "linked", outside)
    assert error_code(lambda: store.create_file("linked", "a.py", "x")) == "PATH_ESCAPE"
    assert list(outside.iterdir()) == []


def test_error_messages_do_not_reveal_host_paths(store, tmp_path):
    messages = []
    for call in (
        lambda: store.read_file(WS, "a.py"),
        lambda: store.create_file(WS, "../a.py", "x"),
        lambda: store.update_file(WS, "missing.py", "x"),
    ):
        try:
            call()
        except WorkspaceError as exc:
            messages.append(exc.message)
    store.create_file(WS, "a.py", "x")
    try:
        store.read_file(WS, "missing.py")
    except WorkspaceError as exc:
        messages.append(exc.message)
    assert messages
    assert all(str(tmp_path) not in m and "workspaces" not in m for m in messages)
