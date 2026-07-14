"""Shared helpers for API route tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from analyst_engine.api.app import create_app
from analyst_engine.config import Settings


def make_settings(*, allow_unauthenticated_write: bool = False) -> Settings:
    return Settings(
        dashscope_api_key="test-key",
        database_url="postgresql+asyncpg://user:pass@localhost/db",
        allow_unauthenticated_write=allow_unauthenticated_write,
    )


def make_runtime(settings: Settings) -> Mock:
    runtime = Mock()
    runtime.settings = settings
    runtime.engine = Mock()
    runtime.session_factory = Mock()
    runtime.gateway = Mock()
    runtime.checkpointer_factory = Mock()
    runtime.close = AsyncMock()
    return runtime


@asynccontextmanager
async def fake_session_scope(_factory: object) -> AsyncIterator[Mock]:
    yield Mock()


def patch_lifespan_services(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ingestion_service: Mock | None = None,
    pipeline: Mock | None = None,
) -> tuple[Mock, Mock]:
    if ingestion_service is None:
        ingestion_service = Mock(ingest_urls=AsyncMock(return_value=[]))
    if pipeline is None:
        pipeline = Mock(run=AsyncMock())
    monkeypatch.setattr("analyst_engine.api.app.session_scope", fake_session_scope)
    monkeypatch.setattr(
        "analyst_engine.api.app.WorkflowRunner",
        Mock(return_value=Mock()),
    )
    monkeypatch.setattr(
        "analyst_engine.api.app.build_ingestion_service",
        Mock(return_value=ingestion_service),
    )
    monkeypatch.setattr(
        "analyst_engine.api.app.build_daily_brief_pipeline",
        Mock(return_value=pipeline),
    )
    return ingestion_service, pipeline


def make_app(
    monkeypatch: pytest.MonkeyPatch,
    *,
    allow_unauthenticated_write: bool = False,
    runtime: Mock | None = None,
    ingestion_service: Mock | None = None,
    pipeline: Mock | None = None,
) -> FastAPI:
    settings = make_settings(allow_unauthenticated_write=allow_unauthenticated_write)
    if runtime is None:
        runtime = make_runtime(settings)
    else:
        runtime.settings = settings
    patch_lifespan_services(
        monkeypatch,
        ingestion_service=ingestion_service,
        pipeline=pipeline,
    )
    return create_app(
        settings_factory=lambda: settings,
        runtime_factory=AsyncMock(return_value=runtime),
        readiness_checker=AsyncMock(),
    )


def make_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    allow_unauthenticated_write: bool = False,
    runtime: Mock | None = None,
    ingestion_service: Mock | None = None,
    pipeline: Mock | None = None,
) -> TestClient:
    app = make_app(
        monkeypatch,
        allow_unauthenticated_write=allow_unauthenticated_write,
        runtime=runtime,
        ingestion_service=ingestion_service,
        pipeline=pipeline,
    )
    client = TestClient(app)
    # Enter the ASGI lifespan explicitly - callers use `client = make_client(...)`
    # directly rather than `with make_client(...) as client:`, and without this
    # the startup lifespan never runs, so app.state.runtime/pipeline/etc. are
    # never populated. Skipping __exit__ is fine here: runtime is a Mock with
    # no real resources, and the process ends with the test session regardless.
    client.__enter__()
    return client
