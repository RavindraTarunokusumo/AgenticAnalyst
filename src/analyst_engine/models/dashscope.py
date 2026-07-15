"""DashScope adapter (OpenAI-compatible endpoint) for the ModelGateway."""

from __future__ import annotations

import json

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

from analyst_engine.config import Settings
from analyst_engine.models.gateway import (
    ModelError,
    ModelGateway,
    ModelTask,
    ModelUsage,
    RetryableModelError,
    TerminalModelError,
)


def _map_api_error(
    exc: Exception, *, task: ModelTask, model: str, correlation_id: str
) -> ModelError:
    """Translate an openai-SDK exception into the ModelGateway error contract.

    Shared by generate() and embed() so both DashScope call sites classify
    provider errors identically (timeout/rate-limit -> retryable, other API
    errors or unexpected exceptions -> terminal).
    """
    if isinstance(exc, (APITimeoutError, RateLimitError)):
        return RetryableModelError(
            f"Retryable DashScope error for {task}: {exc}",
            details={"model": model, "correlation_id": correlation_id},
        )
    if isinstance(exc, APIError):
        return TerminalModelError(
            f"Terminal DashScope error for {task}: {exc}",
            details={
                "model": model,
                "correlation_id": correlation_id,
                "status": getattr(exc, "status_code", None),
            },
        )
    return TerminalModelError(
        f"Unexpected error calling DashScope for {task}",
        details={"correlation_id": correlation_id},
    )


class DashScopeAdapter(ModelGateway):
    """Adapter that routes tasks to the correct Qwen model via DashScope."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        if settings.dashscope_api_key is None:
            raise ValueError("dashscope_api_key is required for DashScopeAdapter")
        self._client = AsyncOpenAI(
            api_key=settings.dashscope_api_key.get_secret_value(),
            base_url=settings.dashscope_base_url,
            timeout=settings.dashscope_timeout_seconds,
            max_retries=settings.dashscope_max_retries,
        )
        self._model_map = {
            ModelTask.BATCH_SUMMARY: settings.batch_summary_model,
            ModelTask.FRONTIER_DAILY: settings.frontier_model,
            ModelTask.FRONTIER_WEEKLY: settings.frontier_model,
            ModelTask.FRONTIER_MONTHLY: settings.frontier_model,
            ModelTask.EMBED: settings.embedding_model,
        }

    def get_model_for_task(self, task: ModelTask) -> str:
        return self._model_map[task]

    async def generate(
        self,
        *,
        task: ModelTask,
        messages: list[dict[str, str]],
        output_schema: type[BaseModel],
        correlation_id: str,
    ) -> tuple[BaseModel, ModelUsage]:
        model = self.get_model_for_task(task)

        try:
            # Use json_object mode + post-validation for broad compatibility
            # (DashScope OpenAI-compatible endpoint supports response_format)
            completion = await self._client.chat.completions.create(  # type: ignore[call-overload]
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=4000,
                extra_headers={"x-correlation-id": correlation_id},
            )
            content = completion.choices[0].message.content or "{}"
            data = json.loads(content)
            result = output_schema.model_validate(data)

            usage = ModelUsage(
                model=model,
                prompt_tokens=completion.usage.prompt_tokens if completion.usage else 0,
                completion_tokens=completion.usage.completion_tokens if completion.usage else 0,
                total_tokens=completion.usage.total_tokens if completion.usage else 0,
            )
            return result, usage

        except (json.JSONDecodeError, ValidationError) as exc:
            # Malformed structured output must never be accepted
            raise TerminalModelError(
                f"Invalid structured output from {model} for {task}",
                details={"correlation_id": correlation_id, "error": str(exc)},
            ) from exc
        except Exception as exc:  # pragma: no cover - safety
            raise _map_api_error(
                exc, task=task, model=model, correlation_id=correlation_id
            ) from exc

    async def embed(self, *, text: str, correlation_id: str) -> tuple[list[float], ModelUsage]:
        model = self.get_model_for_task(ModelTask.EMBED)
        try:
            response = await self._client.embeddings.create(
                model=model,
                input=text,
                extra_headers={"x-correlation-id": correlation_id},
            )
            vector = list(response.data[0].embedding)
            usage = ModelUsage(
                model=model,
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=0,
                total_tokens=response.usage.total_tokens if response.usage else 0,
            )
            return vector, usage
        except Exception as exc:  # pragma: no cover - safety
            raise _map_api_error(
                exc, task=ModelTask.EMBED, model=model, correlation_id=correlation_id
            ) from exc
