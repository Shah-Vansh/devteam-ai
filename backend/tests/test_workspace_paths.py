import pytest

from app.workspace.paths import PathRejected, validate_relative_path, validate_workspace_name


@pytest.mark.parametrize(
    "path",
    [
        "app/main.py",
        "requirements.txt",
        "app/routers/users.py",
        "README.md",
        "App/Config.YAML",
        "console.py",  # starts like CON but is not a device name
        "nul_helpers.py",
        "com10.py",
        "app/data.json",
    ],
)
def test_accepts_safe_relative_paths(path):
    assert validate_relative_path(path) == path


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("", "INVALID_PATH"),
        ("/etc/passwd.txt", "INVALID_PATH"),  # absolute (POSIX)
        ("C:/Windows/win.ini", "INVALID_PATH"),  # drive letter
        ("C:evil.py", "INVALID_PATH"),  # drive-relative
        ("\\\\server\\share\\x.py", "INVALID_PATH"),  # UNC
        ("app\\main.py", "INVALID_PATH"),  # backslash
        ("../x.py", "INVALID_PATH"),
        ("app/../../x.py", "INVALID_PATH"),
        ("./x.py", "INVALID_PATH"),
        ("app//x.py", "INVALID_PATH"),
        ("app/", "INVALID_PATH"),
        (".env.py", "INVALID_PATH"),  # hidden file
        (".git/config.txt", "INVALID_PATH"),  # hidden folder
        ("main.py:hidden", "INVALID_PATH"),  # NTFS alternate data stream
        ("x.py\x00.txt", "INVALID_PATH"),  # null byte
        ("a\tb.py", "INVALID_PATH"),  # control character
        ("a<b.py", "INVALID_PATH"),
        ("a|b.py", "INVALID_PATH"),
        ('a"b.py', "INVALID_PATH"),
        ("a?.py", "INVALID_PATH"),
        ("main.py.", "INVALID_PATH"),  # Windows strips trailing dots
        ("main.py ", "INVALID_PATH"),  # and trailing spaces
        ("con.py", "INVALID_PATH"),  # reserved device names, any case or extension
        ("CON.txt", "INVALID_PATH"),
        ("app/nul.py", "INVALID_PATH"),
        ("aux/x.py", "INVALID_PATH"),
        ("COM1.py", "INVALID_PATH"),
        ("lpt9.md", "INVALID_PATH"),
        ("com\u00b9.py", "INVALID_PATH"),  # COM with superscript one
        ("prn .py", "INVALID_PATH"),
        ("a/" * 8 + "x.py", "INVALID_PATH"),  # too deep
        ("a" * 201 + ".py", "INVALID_PATH"),  # too long
        ("run.exe", "EXTENSION_NOT_ALLOWED"),
        ("script.sh", "EXTENSION_NOT_ALLOWED"),
        ("Makefile", "EXTENSION_NOT_ALLOWED"),
    ],
)
def test_rejects_unsafe_paths(path, code):
    with pytest.raises(PathRejected) as info:
        validate_relative_path(path)
    assert info.value.code == code


def test_path_rejected_is_a_value_error():
    # Pydantic validators turn ValueError into a normal validation error.
    assert issubclass(PathRejected, ValueError)


@pytest.mark.parametrize("name", ["todo-api", "todo_api-3f2a", "a", "x" * 64])
def test_accepts_workspace_names(name):
    assert validate_workspace_name(name) == name


@pytest.mark.parametrize(
    "name", ["", "Todo", "../x", "a/b", "a\\b", "-x", "_x", "x" * 65, "con", "my app", "a.b"]
)
def test_rejects_workspace_names(name):
    with pytest.raises(PathRejected) as info:
        validate_workspace_name(name)
    assert info.value.code == "INVALID_WORKSPACE"
