"""Offline contract tests for the DashScope model adapter's embed() method."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from analyst_engine.config import Settings
from analyst_engine.models.dashscope import DashScopeAdapter
from analyst_engine.models.gateway import ModelTask, RetryableModelError, TerminalModelError

_DATABASE_URL = "postgresql+asyncpg://localhost:5432/analyst_engine"


def _settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
        "dashscope_api_key": "test-dashscope-key",
        "database_url": _DATABASE_URL,
    }
    values.update(overrides)
    return Settings(**values)


def _adapter(handler: httpx.AsyncBaseTransport) -> DashScopeAdapter:
    settings = _settings()
    adapter = DashScopeAdapter(settings)
    http_client = httpx.AsyncClient(transport=handler)
    adapter._client = AsyncOpenAI(
        api_key=settings.dashscope_api_key.get_secret_value(),  # type: ignore[union-attr]
        base_url=settings.dashscope_base_url,
        http_client=http_client,
        max_retries=0,
    )
    return adapter


@pytest.mark.asyncio
async def test_dashscope_embed_returns_vector_and_sends_correlation_header() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/compatible-mode/v1/embeddings"
        assert request.headers["x-correlation-id"] == "corr-embed-1"
        body = json.loads(request.content)
        assert body["model"] == "text-embedding-v4"
        assert body["input"] == "brief text to embed"
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}],
                "model": body["model"],
                "usage": {"prompt_tokens": 4, "total_tokens": 4},
            },
            request=request,
        )

    adapter = _adapter(httpx.MockTransport(handler))
    vector, usage = await adapter.embed(text="brief text to embed", correlation_id="corr-embed-1")

    assert vector == [0.1, 0.2, 0.3]
    assert usage.model == "text-embedding-v4"
    assert usage.prompt_tokens == 4
    assert usage.total_tokens == 4
    assert usage.completion_tokens == 0


@pytest.mark.asyncio
async def test_dashscope_embed_classifies_timeout_as_retryable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    adapter = _adapter(httpx.MockTransport(handler))

    with pytest.raises(RetryableModelError):
        await adapter.embed(text="text", correlation_id="corr-embed-timeout")


@pytest.mark.asyncio
async def test_dashscope_embed_classifies_auth_error_as_terminal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}}, request=request)

    adapter = _adapter(httpx.MockTransport(handler))

    with pytest.raises(TerminalModelError, match=str(ModelTask.EMBED)):
        await adapter.embed(text="text", correlation_id="corr-embed-auth")
