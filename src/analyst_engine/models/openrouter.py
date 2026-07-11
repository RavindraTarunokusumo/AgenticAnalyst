"""OpenRouter adapter for the provider-neutral model gateway."""

from __future__ import annotations

import json

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel, ValidationError

from analyst_engine.config import Settings
from analyst_engine.models.gateway import (
    ModelGateway,
    ModelTask,
    ModelUsage,
    RetryableModelError,
    TerminalModelError,
)


class OpenRouterAdapter(ModelGateway):
    """Route chat tasks through OpenRouter and validate structured responses."""

    def __init__(self, settings: Settings, *, client: AsyncOpenAI | None = None) -> None:
        if settings.openrouter_api_key is None:
            raise ValueError("openrouter_api_key is required for OpenRouterAdapter")
        self._client = client or AsyncOpenAI(
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            timeout=settings.openrouter_timeout_seconds,
            max_retries=settings.openrouter_max_retries,
        )
        self._model_map = {
            ModelTask.BATCH_SUMMARY: settings.openrouter_batch_summary_model,
            ModelTask.FRONTIER_DAILY: settings.openrouter_frontier_model,
            ModelTask.FRONTIER_WEEKLY: settings.openrouter_frontier_model,
            ModelTask.FRONTIER_MONTHLY: settings.openrouter_frontier_model,
        }

    def get_model_for_task(self, task: ModelTask) -> str:
        if task is ModelTask.EMBED:
            raise TerminalModelError("OpenRouter adapter does not support embeddings")
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
            completion = await self._client.chat.completions.create(  # type: ignore[call-overload]
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=4000,
                extra_headers={"x-correlation-id": correlation_id},
            )
            content = completion.choices[0].message.content or "{}"
            result = output_schema.model_validate(json.loads(content))
            usage = ModelUsage(
                model=model,
                prompt_tokens=completion.usage.prompt_tokens if completion.usage else 0,
                completion_tokens=completion.usage.completion_tokens if completion.usage else 0,
                total_tokens=completion.usage.total_tokens if completion.usage else 0,
            )
            return result, usage
        except (APITimeoutError, APIConnectionError) as exc:
            raise RetryableModelError(
                f"Retryable OpenRouter error for {task}",
                details={"model": model, "correlation_id": correlation_id},
            ) from exc
        except APIStatusError as exc:
            error_type = (
                RetryableModelError
                if exc.status_code == 429 or exc.status_code >= 500
                else TerminalModelError
            )
            raise error_type(
                f"OpenRouter HTTP {exc.status_code} for {task}",
                details={
                    "model": model,
                    "correlation_id": correlation_id,
                    "status": exc.status_code,
                },
            ) from exc
        except APIError as exc:
            raise TerminalModelError(
                f"Terminal OpenRouter error for {task}",
                details={"model": model, "correlation_id": correlation_id},
            ) from exc
        except (json.JSONDecodeError, ValidationError) as exc:
            raise TerminalModelError(
                f"Invalid structured output from {model} for {task}",
                details={"correlation_id": correlation_id},
            ) from exc
        except TerminalModelError:
            raise
        except Exception as exc:
            raise TerminalModelError(
                f"Unexpected error calling OpenRouter for {task}",
                details={"correlation_id": correlation_id},
            ) from exc
