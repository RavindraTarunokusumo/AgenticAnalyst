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
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)


class ProcessMode(StrEnum):
    """Application process mode for API delivery or scheduler execution."""

    API = "api"
    SCHEDULER = "scheduler"


class ModelProvider(StrEnum):
    """Supported model gateway providers."""

    DASHSCOPE = "dashscope"
    OPENROUTER = "openrouter"


class Settings(BaseSettings):
    """Validated runtime configuration for AnalystEngine."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,
    )

    model_provider: ModelProvider = Field(
        default=ModelProvider.DASHSCOPE,
        description="Model gateway provider.",
    )
    dashscope_api_key: SecretStr | None = Field(
        default=None,
        description="DashScope API key for OpenAI-compatible endpoint access.",
    )
    dashscope_base_url: str = Field(
        default=DEFAULT_DASHSCOPE_BASE_URL,
        description="DashScope OpenAI-compatible base URL.",
    )
    openrouter_api_key: SecretStr | None = Field(
        default=None,
        description="OpenRouter API key for OpenAI-compatible endpoint access.",
    )
    openrouter_base_url: str = Field(
        default=DEFAULT_OPENROUTER_BASE_URL,
        description="OpenRouter OpenAI-compatible base URL.",
    )
    openrouter_frontier_model: str = Field(
        default="tencent/hy3:free",
        description="OpenRouter model for frontier synthesis.",
    )
    openrouter_batch_summary_model: str = Field(
        default="cohere/north-mini-code:free",
        description="OpenRouter model for batch summaries.",
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
    openrouter_timeout_seconds: float = Field(
        default=120.0,
        gt=0,
        description="Timeout for OpenRouter calls (seconds).",
    )
    openrouter_max_retries: int = Field(
        default=3,
        ge=0,
        description="Max retries for retryable OpenRouter errors.",
    )

    # Ingestion / batching / pipeline
    feed_request_timeout_seconds: float = Field(
        default=15.0,
        gt=0,
        description="Timeout for feed HTTP requests (seconds).",
    )
    feed_response_size_limit_bytes: int = Field(
        default=5_000_000,
        gt=0,
        description="Maximum accepted feed document size in bytes.",
    )
    feed_user_agent: str = Field(
        default="AnalystEngine/0.1 (+https://github.com/RavindraTarunokusumo/AgenticAnalyst)",
        description="User-Agent header sent to feeds and article sources.",
    )
    default_poll_interval_minutes: int = Field(
        default=30,
        gt=0,
        description="Default polling interval for a newly registered feed.",
    )
    article_min_content_length: int = Field(
        default=200,
        gt=0,
        description="Minimum cleaned-content length for an article to be accepted.",
    )
    article_max_response_size_bytes: int = Field(
        default=10_000_000,
        gt=0,
        description="Maximum accepted article page response size in bytes.",
    )
    allowed_languages: list[str] = Field(
        default_factory=lambda: ["en"],
        description="Languages eligible for batching; other languages may be stored but excluded.",
    )
    title_similarity_threshold: float = Field(
        default=0.35,
        gt=0,
        le=1,
        description="Title-token Jaccard similarity threshold for batch grouping.",
    )
    grouping_algorithm_version: str = Field(
        default="v1",
        description="Version tag for the deterministic batching algorithm.",
    )
    batch_summary_prompt_version: str = Field(
        default="v1",
        description="Version tag for the batch-summary prompt template.",
    )
    max_feeds_per_run: int = Field(
        default=50,
        gt=0,
        description="Maximum feeds polled per pipeline run.",
    )
    max_articles_per_run: int = Field(
        default=200,
        gt=0,
        description="Maximum articles selected for batching per pipeline run.",
    )
    allow_unauthenticated_write: bool = Field(
        default=False,
        description="Explicit local-development opt-in to accept write/trigger requests "
        "without an API key. Must stay false outside local development.",
    )

    @field_validator("allowed_languages")
    @classmethod
    def validate_allowed_languages(cls, value: list[str]) -> list[str]:
        if not value:
            msg = "allowed_languages must not be empty"
            raise ValueError(msg)
        return value

    @field_validator("dashscope_api_key", "openrouter_api_key", mode="before")
    @classmethod
    def normalize_optional_provider_key(cls, value: object) -> object | None:
        if isinstance(value, SecretStr):
            return value if value.get_secret_value().strip() else None
        if isinstance(value, str):
            return value if value.strip() else None
        return value

    @field_validator("dashscope_base_url", "openrouter_base_url")
    @classmethod
    def validate_dashscope_base_url(cls, value: str) -> str:
        try:
            parsed_url = _HTTP_URL_ADAPTER.validate_python(value)
        except ValidationError as error:
            msg = "provider base URL must be a valid HTTPS URL with a host"
            raise ValueError(msg) from error
        if parsed_url.scheme != "https":
            msg = "provider base URL must be an HTTPS URL"
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
    def validate_provider_credentials(self) -> Self:
        if self.model_provider is ModelProvider.DASHSCOPE and self.dashscope_api_key is None:
            msg = "dashscope_api_key is required when model_provider is dashscope"
            raise ValueError(msg)
        if self.model_provider is ModelProvider.OPENROUTER and self.openrouter_api_key is None:
            msg = "openrouter_api_key is required when model_provider is openrouter"
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
