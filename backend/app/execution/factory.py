"""Choose the executor from settings. A missing key falls back to static-only, which
reports NOT_EXECUTED rather than pretending tests passed."""

from app.core.config import Settings
from app.execution.base import CodeExecutor
from app.execution.e2b_executor import E2BExecutor
from app.execution.static_only import StaticOnlyExecutor


def build_executor(settings: Settings) -> CodeExecutor:
    if settings.executor == "e2b":
        if settings.e2b_api_key is None:
            return StaticOnlyExecutor("EXECUTOR=e2b but E2B_API_KEY is not set")
        return E2BExecutor(settings.e2b_api_key.get_secret_value())
    return StaticOnlyExecutor("EXECUTOR=static_only")
