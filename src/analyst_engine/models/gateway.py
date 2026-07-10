"""Provider-neutral model gateway and contracts.

LangGraph nodes and workflows call only through ModelGateway.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, Type

from pydantic import BaseModel, Field


class ModelTask(StrEnum):
    """Responsibilities that map to specific models."""

    BATCH_SUMMARY = "batch_summary"  # qwen3.5-flash
    FRONTIER_DAILY = "frontier_daily"  # qwen3.7-max
    FRONTIER_WEEKLY = "frontier_weekly"
    FRONTIER_MONTHLY = "frontier_monthly"
    EMBED = "embed"  # text-embedding-v4


class ModelUsage(BaseModel):
    """Token and model usage returned by the provider."""

    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ModelError(Exception):
    """Base for provider errors."""

    def __init__(self, message: str, *, retryable: bool = False, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.details = details or {}


class RetryableModelError(ModelError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message, retryable=True, details=details)


class TerminalModelError(ModelError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message, retryable=False, details=details)


class ModelGateway(ABC):
    """Narrow boundary for all model calls. Returns validated Pydantic output."""

    @abstractmethod
    async def generate(
        self,
        *,
        task: ModelTask,
        messages: list[dict[str, str]],
        output_schema: Type[BaseModel],
        correlation_id: str,
    ) -> tuple[BaseModel, ModelUsage]:
        """Call the appropriate model, enforce structured output, return (result, usage).

        Raises RetryableModelError or TerminalModelError on failure.
        Must not persist state.
        """
        ...

    @abstractmethod
    def get_model_for_task(self, task: ModelTask) -> str:
        """Return the concrete model identifier for the task."""
        ...
