"""Run a generated API in an E2B microVM so a person can try it in the browser.

Same rules as the test sandbox: generated code never runs on the host, no environment
variables (no secrets) go in, packages come from the allow-list pinned by the constraints
file, and outbound internet is switched off before the app starts. What differs: the app's
port is reachable from the internet through E2B's URL for a few minutes, so the person who
clicked "Try the API" can open its /docs page. The sandbox deletes itself when that time is
up, or earlier when they stop it.
"""

import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from e2b import CommandExitException, Sandbox, SandboxException

from app.execution.packages import TEST_PACKAGES, select_packages
from app.workspace.paths import validate_relative_path

HOME = "/home/user"
PROJECT_DIR = f"{HOME}/project"
CONSTRAINTS_PATH = f"{HOME}/constraints.txt"
APP_PORT = 8000
INSTALL_TIMEOUT_SECONDS = 240
STARTUP_TIMEOUT_SECONDS = 30
PREVIEW_MINUTES = 10
ENTRY_FILE = "app/main.py"  # every generated project has its FastAPI app here


class PreviewError(Exception):
    """The app could not be started; the message says why."""


@dataclass
class PreviewHandle:
    url: str
    expires_at: float  # time.time()
    sandbox: Any


def install_list(requirements_text: str) -> list[str]:
    """Allowed packages from requirements.txt, plus the server; test-only ones are skipped."""
    selection = select_packages(requirements_text)
    packages = [p for p in selection.install if p not in TEST_PACKAGES]
    if "uvicorn" not in packages:
        packages.append("uvicorn")
    return packages


class E2BPreview:
    def __init__(
        self,
        api_key: str,
        constraints_text: str,
        *,
        sandbox_factory: Callable[..., Any] = Sandbox.create,
        minutes: int = PREVIEW_MINUTES,
    ) -> None:
        self._api_key = api_key
        self._constraints = constraints_text
        self._create = sandbox_factory
        self._minutes = minutes

    def start(self, files: dict[str, str]) -> PreviewHandle:
        if ENTRY_FILE not in files:
            raise PreviewError(f"the project has no {ENTRY_FILE}")
        for path in files:
            validate_relative_path(path)  # raises ValueError for anything outside the folder

        sandbox = self._create(
            api_key=self._api_key,
            timeout=self._minutes * 60 + INSTALL_TIMEOUT_SECONDS,
            network={"allow_public_traffic": True},
        )
        try:
            for path, content in files.items():
                sandbox.files.write(f"{PROJECT_DIR}/{path}", content)
            sandbox.files.write(CONSTRAINTS_PATH, self._constraints)
            wanted = install_list(files.get("requirements.txt", ""))
            packages = " ".join(shlex.quote(p) for p in wanted)
            try:
                sandbox.commands.run(
                    "pip install --no-input --disable-pip-version-check -q "
                    f"-c {CONSTRAINTS_PATH} {packages}",
                    timeout=INSTALL_TIMEOUT_SECONDS,
                )
            except CommandExitException as exc:
                raise PreviewError(f"package installation failed: {exc.stderr[-300:]}") from exc

            sandbox.update_network({"allow_internet_access": False})
            sandbox.commands.run(
                f"python -m uvicorn app.main:app --host 0.0.0.0 --port {APP_PORT}",
                cwd=PROJECT_DIR,
                background=True,
            )
            self._wait_until_up(sandbox)
            # The full time starts now, after installing (the sandbox's own timeout is the
            # backstop and includes the install time).
            sandbox.set_timeout(self._minutes * 60)
            return PreviewHandle(
                url=f"https://{sandbox.get_host(APP_PORT)}",
                expires_at=time.time() + self._minutes * 60,
                sandbox=sandbox,
            )
        except BaseException:
            stop(sandbox)
            raise

    @staticmethod
    def _wait_until_up(sandbox: Any) -> None:
        probe = (
            'python -c "import urllib.request; '
            f"urllib.request.urlopen('http://127.0.0.1:{APP_PORT}/openapi.json', timeout=2)\""
        )
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while True:
            try:
                sandbox.commands.run(probe, timeout=10)
                return
            except (CommandExitException, SandboxException) as exc:
                if time.monotonic() > deadline:
                    raise PreviewError(
                        f"the app did not start within {STARTUP_TIMEOUT_SECONDS}s"
                    ) from exc
                time.sleep(1)


def stop(sandbox: Any) -> None:
    try:
        sandbox.kill()
    except Exception:  # noqa: S110 - it also deletes itself when its timeout ends
        pass
