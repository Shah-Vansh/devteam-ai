from pathlib import Path

from app.core.config import REPO_ROOT, Settings


def make_settings(tmp_path: Path, content: str) -> Settings:
    env_file = tmp_path / ".env"
    env_file.write_text(content, encoding="utf-8")
    return Settings(_env_file=env_file)


def test_reads_values_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    settings = make_settings(tmp_path, "LLM_PROVIDER=groq\nLLM_MODEL=some-model\n")
    assert settings.llm_provider == "groq"
    assert settings.llm_model == "some-model"


def test_empty_values_become_none(tmp_path, monkeypatch):
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "E2B_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    settings = make_settings(tmp_path, "LLM_API_KEY=\nLLM_BASE_URL=\nE2B_API_KEY=\n")
    assert settings.llm_api_key is None
    assert settings.llm_base_url is None
    assert settings.e2b_api_key is None


def test_relative_paths_resolve_from_repo_root(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKSPACES_DIR", raising=False)
    settings = make_settings(tmp_path, "WORKSPACES_DIR=./workspaces\n")
    assert settings.workspaces_dir == (REPO_ROOT / "workspaces").resolve()


def test_secrets_are_hidden_in_repr(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    settings = make_settings(tmp_path, "LLM_API_KEY=very-secret-value\n")
    assert "very-secret-value" not in repr(settings)
    assert settings.secret_values() == ["very-secret-value"]


def test_frontend_values_are_ignored(tmp_path):
    settings = make_settings(tmp_path, "VITE_API_BASE_URL=http://127.0.0.1:8000\n")
    assert not hasattr(settings, "vite_api_base_url")


def test_cors_origin_list(tmp_path, monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    settings = make_settings(tmp_path, "CORS_ORIGINS=http://a.test, http://b.test\n")
    assert settings.cors_origin_list == ["http://a.test", "http://b.test"]
