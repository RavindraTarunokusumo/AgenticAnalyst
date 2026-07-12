"""Settings configuration validation tests."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from analyst_engine.config import (
    DEFAULT_DASHSCOPE_BASE_URL,
    DEFAULT_OPENROUTER_BASE_URL,
    ModelProvider,
    ProcessMode,
    Settings,
)

_VALID_DATABASE_URL = "postgresql+asyncpg://localhost:5432/analyst_engine"
_VALID_DASHSCOPE_KEY = "test-dashscope-key"


def test_settings_loads_with_required_environment_variables() -> None:
    settings = Settings(
        dashscope_api_key=_VALID_DASHSCOPE_KEY,
        database_url=_VALID_DATABASE_URL,
    )

    assert settings.dashscope_base_url == DEFAULT_DASHSCOPE_BASE_URL
    assert settings.langsmith_tracing is False
    assert settings.langsmith_project == "analyst-engine-local"
    assert settings.app_process_mode == ProcessMode.API
    assert settings.temporal_evaluation_enabled is False
    assert settings.temporal_evaluation_model == "qwen3.7-max-preview"


def test_settings_loads_with_all_optional_configuration() -> None:
    settings = Settings(
        dashscope_api_key=_VALID_DASHSCOPE_KEY,
        database_url=_VALID_DATABASE_URL,
        langsmith_tracing=True,
        langsmith_api_key="test-langsmith-key",  # pragma: allowlist secret
        langsmith_project="evaluation-project",
        app_process_mode=ProcessMode.SCHEDULER,
        temporal_evaluation_enabled=True,
        temporal_evaluation_cutoff_date="2026-05-01",
        temporal_evaluation_corpus_path="fixtures/holdout.jsonl",
    )

    assert settings.langsmith_tracing is True
    assert settings.app_process_mode == ProcessMode.SCHEDULER
    assert str(settings.temporal_evaluation_cutoff_date) == "2026-05-01"
    assert settings.temporal_evaluation_corpus_path == Path("fixtures/holdout.jsonl")


def test_settings_rejects_missing_dashscope_api_key() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(database_url=_VALID_DATABASE_URL)

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ()
    assert "dashscope_api_key is required" in errors[0]["msg"]


def test_settings_rejects_missing_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError) as exc_info:
        Settings(dashscope_api_key=_VALID_DASHSCOPE_KEY)

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("database_url",)
    assert errors[0]["type"] == "missing"


def test_settings_rejects_empty_dashscope_api_key() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(dashscope_api_key="   ", database_url=_VALID_DATABASE_URL)

    errors = exc_info.value.errors()
    assert errors[0]["loc"] == ()
    assert "dashscope_api_key is required" in errors[0]["msg"]


@pytest.mark.parametrize(
    "dashscope_base_url",
    [
        "http://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "https://",
        "not a URL",
    ],
)
def test_settings_rejects_invalid_dashscope_base_url(dashscope_base_url: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            dashscope_api_key=_VALID_DASHSCOPE_KEY,
            database_url=_VALID_DATABASE_URL,
            dashscope_base_url=dashscope_base_url,
        )

    assert exc_info.value.errors()[0]["loc"] == ("dashscope_base_url",)


def test_settings_normalizes_dashscope_base_url_trailing_slash() -> None:
    settings = Settings(
        dashscope_api_key=_VALID_DASHSCOPE_KEY,
        database_url=_VALID_DATABASE_URL,
        dashscope_base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1/",
    )

    assert settings.dashscope_base_url == DEFAULT_DASHSCOPE_BASE_URL


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite+aiosqlite:///analyst_engine.db",
        "not a database URL",
        "postgresql://localhost:5432/analyst_engine",
        "postgres://localhost:5432/analyst_engine",
    ],
)
def test_settings_rejects_non_postgresql_database_url(database_url: str) -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            dashscope_api_key=_VALID_DASHSCOPE_KEY,
            database_url=database_url,
        )

    assert exc_info.value.errors()[0]["loc"] == ("database_url",)


def test_settings_rejects_langsmith_api_key_when_tracing_enabled() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            dashscope_api_key=_VALID_DASHSCOPE_KEY,
            database_url=_VALID_DATABASE_URL,
            langsmith_tracing=True,
        )

    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ()
    assert "langsmith_api_key is required when langsmith_tracing is enabled" in errors[0]["msg"]


def test_settings_rejects_incomplete_temporal_evaluation_configuration() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            dashscope_api_key=_VALID_DASHSCOPE_KEY,
            database_url=_VALID_DATABASE_URL,
            temporal_evaluation_enabled=True,
        )

    errors = exc_info.value.errors()
    assert errors[0]["loc"] == ()
    assert "temporal_evaluation_cutoff_date is required" in errors[0]["msg"]


def test_settings_loads_openrouter_provider_defaults_without_dashscope_key() -> None:
    settings = Settings(
        model_provider=ModelProvider.OPENROUTER,
        openrouter_api_key="test-openrouter-key",
        database_url=_VALID_DATABASE_URL,
    )

    assert settings.openrouter_base_url == DEFAULT_OPENROUTER_BASE_URL
    assert settings.openrouter_frontier_model == "tencent/hy3:free"
    assert settings.openrouter_batch_summary_model == "cohere/north-mini-code:free"
    assert settings.openrouter_timeout_seconds == 120.0
    assert settings.openrouter_max_retries == 3


def test_settings_requires_key_for_selected_provider() -> None:
    with pytest.raises(ValidationError, match="openrouter_api_key is required"):
        Settings(model_provider="openrouter", database_url=_VALID_DATABASE_URL)


def test_settings_allows_blank_inactive_openrouter_key_for_dashscope() -> None:
    settings = Settings(
        model_provider="dashscope",
        dashscope_api_key=_VALID_DASHSCOPE_KEY,
        openrouter_api_key="",
        database_url=_VALID_DATABASE_URL,
    )

    assert settings.openrouter_api_key is None


def test_settings_allows_blank_inactive_dashscope_key_for_openrouter() -> None:
    settings = Settings(
        model_provider="openrouter",
        dashscope_api_key="",
        openrouter_api_key="test-openrouter-key",
        database_url=_VALID_DATABASE_URL,
    )

    assert settings.dashscope_api_key is None


@pytest.mark.parametrize(
    "provider,key_field",
    [("dashscope", "dashscope_api_key"), ("openrouter", "openrouter_api_key")],
)
def test_settings_rejects_blank_selected_provider_key(provider: str, key_field: str) -> None:
    provider_settings: dict[str, Any] = {
        "model_provider": provider,
        "database_url": _VALID_DATABASE_URL,
        key_field: "",
    }
    with pytest.raises(ValidationError, match=f"{key_field} is required"):
        Settings(**provider_settings)


def test_settings_never_exposes_openrouter_secret() -> None:
    secret = "test-openrouter-secret"
    settings = Settings(
        model_provider="openrouter",
        openrouter_api_key=secret,
        database_url=_VALID_DATABASE_URL,
    )

    assert secret not in repr(settings)
    assert secret not in str(settings.model_dump())
