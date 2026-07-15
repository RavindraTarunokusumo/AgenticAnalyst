"""Offline contract tests for the OpenRouter model adapter."""

import hashlib
import hmac
import json
import os
from typing import Any, cast

import httpx
import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel

from analyst_engine.config import Settings
from analyst_engine.models import ModelGateway, ModelTask, RetryableModelError, TerminalModelError
from analyst_engine.models.factory import create_model_gateway
from analyst_engine.models.openrouter import OpenRouterAdapter

_DATABASE_URL = "postgresql+asyncpg://localhost:5432/analyst_engine"


class Result(BaseModel):
    answer: str


def _settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
        "model_provider": "openrouter",
        "openrouter_api_key": "test-openrouter-key",
        "database_url": _DATABASE_URL,
    }
    values.update(overrides)
    return Settings(**values)


def _adapter(handler: httpx.AsyncBaseTransport) -> OpenRouterAdapter:
    settings = _settings()
    http_client = httpx.AsyncClient(transport=handler)
    client = AsyncOpenAI(
        api_key=settings.openrouter_api_key.get_secret_value(),  # type: ignore[union-attr]
        base_url=settings.openrouter_base_url,
        http_client=http_client,
        max_retries=0,
    )
    return OpenRouterAdapter(settings, client=client)


def test_factory_returns_selected_model_gateway() -> None:
    gateway = create_model_gateway(_settings())

    assert isinstance(gateway, ModelGateway)
    assert isinstance(gateway, OpenRouterAdapter)


def test_openrouter_routes_frontier_and_batch_models() -> None:
    adapter = OpenRouterAdapter(_settings())

    assert adapter.get_model_for_task(ModelTask.FRONTIER_DAILY) == "tencent/hy3:free"
    assert adapter.get_model_for_task(ModelTask.FRONTIER_WEEKLY) == "tencent/hy3:free"
    assert adapter.get_model_for_task(ModelTask.FRONTIER_MONTHLY) == "tencent/hy3:free"
    assert adapter.get_model_for_task(ModelTask.BATCH_SUMMARY) == "cohere/north-mini-code:free"


def test_openrouter_routes_configured_alternative_models() -> None:
    adapter = OpenRouterAdapter(
        _settings(
            openrouter_frontier_model="nvidia/nemotron-3-ultra-550b-a55b:free",
            openrouter_batch_summary_model="google/gemma-4-31b-it:free",
        )
    )

    assert (
        adapter.get_model_for_task(ModelTask.FRONTIER_DAILY)
        == "nvidia/nemotron-3-ultra-550b-a55b:free"
    )
    assert adapter.get_model_for_task(ModelTask.BATCH_SUMMARY) == "google/gemma-4-31b-it:free"


@pytest.mark.asyncio
async def test_openrouter_validates_structured_output_and_sends_correlation_header() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.scheme == "https"
        assert request.url.host == "openrouter.ai"
        assert request.url.path == "/api/v1/chat/completions"
        assert request.headers["x-correlation-id"] == "corr-123"
        actual_auth_digest = hashlib.sha256(request.headers["authorization"].encode()).digest()
        expected_auth_digest = hashlib.sha256(b"Bearer test-openrouter-key").digest()
        assert hmac.compare_digest(actual_auth_digest, expected_auth_digest)
        body = json.loads(request.content)
        assert body["model"] == "tencent/hy3:free"
        return httpx.Response(
            200,
            json={
                "id": "completion-1",
                "object": "chat.completion",
                "created": 1,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"answer":"ok"}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
            },
            request=request,
        )

    adapter = _adapter(httpx.MockTransport(handler))
    result, usage = await adapter.generate(
        task=ModelTask.FRONTIER_DAILY,
        messages=[{"role": "user", "content": "answer"}],
        output_schema=Result,
        correlation_id="corr-123",
    )

    assert result == Result(answer="ok")
    assert usage.total_tokens == 5


@pytest.mark.asyncio
async def test_openrouter_rejects_embed_without_http_request() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500, request=request)

    adapter = _adapter(httpx.MockTransport(handler))

    with pytest.raises(TerminalModelError, match="does not support embeddings"):
        await adapter.generate(
            task=ModelTask.EMBED,
            messages=[],
            output_schema=Result,
            correlation_id="corr-embed",
        )

    assert called is False


@pytest.mark.asyncio
async def test_openrouter_embed_rejects_without_http_request() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500, request=request)

    adapter = _adapter(httpx.MockTransport(handler))

    with pytest.raises(TerminalModelError, match="does not support embeddings"):
        await adapter.embed(text="query text", correlation_id="corr-embed-2")

    assert called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_openrouter_classifies_transient_http_errors_as_retryable(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "temporary"}}, request=request)

    adapter = _adapter(httpx.MockTransport(handler))

    with pytest.raises(RetryableModelError):
        await adapter.generate(
            task=ModelTask.BATCH_SUMMARY,
            messages=[],
            output_schema=Result,
            correlation_id="corr-retry",
        )


@pytest.mark.asyncio
async def test_openrouter_rejects_invalid_structured_output_as_terminal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "completion-1",
                "object": "chat.completion",
                "created": 1,
                "model": "cohere/north-mini-code:free",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "{}"},
                        "finish_reason": "stop",
                    }
                ],
            },
            request=request,
        )

    adapter = _adapter(httpx.MockTransport(handler))

    with pytest.raises(TerminalModelError, match="Invalid structured output"):
        await adapter.generate(
            task=ModelTask.BATCH_SUMMARY,
            messages=[],
            output_schema=Result,
            correlation_id="corr-invalid",
        )


@pytest.mark.live_openrouter
@pytest.mark.asyncio
async def test_openrouter_live_structured_output_smoke() -> None:
    if os.getenv("RUN_OPENROUTER_LIVE_SMOKE") != "1":
        pytest.skip("set RUN_OPENROUTER_LIVE_SMOKE=1 to enable the live smoke test")
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY is not available")

    adapter = OpenRouterAdapter(
        _settings(
            openrouter_api_key=api_key,
            openrouter_batch_summary_model=os.getenv(
                "OPENROUTER_BATCH_SUMMARY_MODEL", "cohere/north-mini-code:free"
            ),
        )
    )
    result, _ = await adapter.generate(
        task=ModelTask.BATCH_SUMMARY,
        messages=[{"role": "user", "content": "Return JSON with answer set to ok."}],
        output_schema=Result,
        correlation_id="live-openrouter-smoke",
    )

    assert cast(Result, result).answer == "ok"
