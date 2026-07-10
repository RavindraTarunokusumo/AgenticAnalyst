"""Typed application settings loaded from environment variables."""

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import (
    Field,
    HttpUrl,
    PostgresDsn,
    SecretStr,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


class ProcessMode(StrEnum):
    """Application process mode for API delivery or scheduler execution."""

    API = "api"
    SCHEDULER = "scheduler"


class Settings(BaseSettings):
    """Validated runtime configuration for AnalystEngine."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    dashscope_api_key: SecretStr = Field(
        description="DashScope API key for OpenAI-compatible endpoint access.",
    )
    dashscope_base_url: str = Field(
        default=DEFAULT_DASHSCOPE_BASE_URL,
        description="DashScope OpenAI-compatible base URL.",
    )

    database_url: PostgresDsn = Field(
        description="PostgreSQL connection URL for the system of record.",
    )

    langsmith_tracing: bool = Field(
        default=False,
        description="Enable LangSmith tracing for workflow and model calls.",
    )
    langsmith_api_key: SecretStr | None = Field(
        default=None,
        description="LangSmith API key; required when tracing is enabled.",
    )
    langsmith_project: str = Field(
        default="analyst-engine-local",
        description="LangSmith project name for traces.",
    )
    langsmith_endpoint: str | None = Field(
        default=None,
        description="Optional LangSmith API endpoint override.",
    )

    app_process_mode: ProcessMode = Field(
        default=ProcessMode.API,
        description="Application process mode: api or scheduler.",
    )

    temporal_evaluation_enabled: bool = Field(
        default=False,
        description="Enable opt-in temporal holdout evaluation runs.",
    )
    temporal_evaluation_model: str = Field(
        default="qwen3.7-max-preview",
        description="Frontier model identifier for temporal evaluation.",
    )
    temporal_evaluation_cutoff_date: date | None = Field(
        default=None,
        description="Documented model knowledge cut-off date (ISO 8601).",
    )
    temporal_evaluation_corpus_path: Path | None = Field(
        default=None,
        description="Path to frozen evaluation corpus manifest.",
    )

    # Model routing (fixed per design)
    batch_summary_model: str = Field(
        default="qwen3.5-flash",
        description="Model for batch summaries of 3-5 articles.",
    )
    frontier_model: str = Field(
        default="qwen3.7-max",
        description="Model for daily/weekly/monthly frontier synthesis.",
    )
    embedding_model: str = Field(
        default="text-embedding-v4",
        description="Model for brief archive embeddings.",
    )

    # Provider behavior
    dashscope_timeout_seconds: float = Field(
        default=120.0,
        description="Timeout for DashScope calls (seconds).",
    )
    dashscope_max_retries: int = Field(
        default=3,
        description="Max retries for retryable provider errors.",
    )

    @field_validator("dashscope_api_key")
    @classmethod
    def validate_dashscope_api_key(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            msg = "dashscope_api_key must not be empty"
            raise ValueError(msg)
        return value

    @field_validator("dashscope_base_url")
    @classmethod
    def validate_dashscope_base_url(cls, value: str) -> str:
        try:
            parsed_url = _HTTP_URL_ADAPTER.validate_python(value)
        except ValidationError as error:
            msg = "dashscope_base_url must be a valid HTTPS URL with a host"
            raise ValueError(msg) from error
        if parsed_url.scheme != "https":
            msg = "dashscope_base_url must be an HTTPS URL"
            raise ValueError(msg)
        return str(parsed_url).rstrip("/")

    @field_validator("database_url")
    @classmethod
    def validate_database_url_driver(cls, value: PostgresDsn) -> PostgresDsn:
        if value.scheme != "postgresql+asyncpg":
            msg = "database_url must use the postgresql+asyncpg scheme"
            raise ValueError(msg)
        return value

    @field_validator("langsmith_api_key")
    @classmethod
    def validate_langsmith_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value().strip():
            msg = "langsmith_api_key must not be empty when supplied"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_langsmith_credentials(self) -> Self:
        if self.langsmith_tracing and self.langsmith_api_key is None:
            msg = "langsmith_api_key is required when langsmith_tracing is enabled"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def validate_evaluation_configuration(self) -> Self:
        if self.temporal_evaluation_enabled:
            if self.temporal_evaluation_cutoff_date is None:
                msg = (
                    "temporal_evaluation_cutoff_date is required when "
                    "temporal_evaluation_enabled is true"
                )
                raise ValueError(msg)
            if self.temporal_evaluation_corpus_path is None:
                msg = (
                    "temporal_evaluation_corpus_path is required when "
                    "temporal_evaluation_enabled is true"
                )
                raise ValueError(msg)
        return self
