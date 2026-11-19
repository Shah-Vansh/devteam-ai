"""Application settings loaded from the single root .env file.

Every component (backend, MCP servers, scripts) gets its configuration through
`get_settings()`. Values come from, in order of priority:
1. real environment variables,
2. the root `.env` file,
3. the defaults below.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents: core, app, backend, <repo root>
REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",  # the shared .env also holds frontend (VITE_) values
    )

    # Shared
    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Backend
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    database_url: str = "sqlite:///./data/devteam.db"
    checkpoint_db_path: Path = Path("./data/checkpoints.db")
    workspaces_dir: Path = Path("./workspaces")
    cors_origins: str = "http://localhost:5173"

    # LLM
    llm_provider: str = ""
    llm_api_key: SecretStr | None = None
    llm_model: str = ""
    llm_base_url: str | None = None
    llm_timeout_seconds: float = 120.0
    llm_max_output_tokens: int | None = None
    llm_reasoning_effort: Literal["low", "medium", "high"] | None = None

    # Execution sandbox
    executor: Literal["e2b", "static_only"] = "static_only"
    e2b_api_key: SecretStr | None = None
    sandbox_timeout_seconds: int = 120

    # Commits in generated projects (local history only, never pushed)
    commit_author_name: str = "DevTeam AI"
    commit_author_email: str = "devteam-ai@localhost"

    # Workflow limits
    max_review_rounds: int = 2
    max_fix_rounds: int = 2
    max_llm_calls_per_run: int = 40

    @field_validator(
        "llm_api_key",
        "e2b_api_key",
        "llm_base_url",
        "llm_max_output_tokens",
        "llm_reasoning_effort",
        mode="before",
    )
    @classmethod
    def empty_to_none(cls, value: object) -> object:
        """An empty line like `LLM_BASE_URL=` in .env means "not set", not "empty string"."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("checkpoint_db_path", "workspaces_dir", mode="after")
    @classmethod
    def resolve_from_repo_root(cls, value: Path) -> Path:
        """Relative paths are relative to the repo root, not to the current directory."""
        return value if value.is_absolute() else (REPO_ROOT / value).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def secret_values(self) -> list[str]:
        """Raw secret strings, used by the logging filter to redact them."""
        secrets = [self.llm_api_key, self.e2b_api_key]
        return [s.get_secret_value() for s in secrets if s is not None]


@lru_cache
def get_settings() -> Settings:
    """Settings are read once per process and then reused."""
    return Settings()
