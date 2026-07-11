"""Settings configuration validation tests."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from analyst_engine.config import DEFAULT_DASHSCOPE_BASE_URL, ProcessMode, Settings

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
    assert errors[0]["loc"] == ("dashscope_api_key",)
    assert errors[0]["type"] == "missing"


def test_settings_rejects_missing_database_url() -> None:
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
    assert errors[0]["loc"] == ("dashscope_api_key",)
    assert "dashscope_api_key must not be empty" in errors[0]["msg"]


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
