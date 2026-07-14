"""FastAPI application factory with health, readiness, and manual triggers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine

from analyst_engine.api.readiness import ReadinessStatus, check_readiness
from analyst_engine.config import Settings
from analyst_engine.runtime import (
    RuntimeDependencies,
    build_daily_brief_pipeline,
    build_ingestion_service,
    create_runtime,
)
from analyst_engine.workflows.runner import WorkflowRunner

# Very simple harness auth (token from env or header for local dev)
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


class TriggerRequest(BaseModel):
    cadence: str
    covered_start: date
    covered_end: date


class TriggerResponse(BaseModel):
    run_id: str
    status: str
    idempotency_key: str


def get_settings() -> Settings:
    # In real app this would be injected from lifespan or dependency
    return Settings()  # relies on .env


def create_app(
    *,
    settings_factory: Callable[[], Settings] = get_settings,
    runtime_factory: Callable[[Settings], Awaitable[RuntimeDependencies]] = create_runtime,
    readiness_checker: Callable[[AsyncEngine], Awaitable[ReadinessStatus]] = check_readiness,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = await runtime_factory(settings_factory())
        try:
            runner = WorkflowRunner(
                runtime.settings,
                runtime.gateway,
                runtime.session_factory,
                runtime.checkpointer_factory,
            )
            ingestion_service = build_ingestion_service(runtime)
            pipeline = build_daily_brief_pipeline(
                runtime,
                ingestion_service=ingestion_service,
                runner=runner,
            )
            app.state.runtime = runtime
            app.state.engine = runtime.engine
            app.state.runner = runner
            app.state.ingestion_service = ingestion_service
            app.state.pipeline = pipeline
            yield
        finally:
            await runtime.close()

    app = FastAPI(title="AnalystEngine Harness", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        runtime: RuntimeDependencies = app.state.runtime
        readiness = await readiness_checker(runtime.engine)
        return JSONResponse(
            status_code=200 if readiness.status == "ready" else 503,
            content=readiness.model_dump(exclude_none=True),
        )

    async def _require_key(key: str | None = Security(API_KEY_HEADER)) -> str:
        # For harness: accept any non-empty or allow open in local
        if key is None or not key.strip():
            # Allow unauthenticated in pure local harness mode
            return "local"
        return key

    @app.post("/workflows/trigger", response_model=TriggerResponse)
    async def trigger(
        req: TriggerRequest,
        _key: str = Depends(_require_key),
    ) -> TriggerResponse:
        # settings = get_settings()  # available if needed for future
        runner: WorkflowRunner = app.state.runner
        if req.cadence == "daily":
            run = await runner.run_daily(req.covered_start)
        elif req.cadence == "weekly":
            run = await runner.run_weekly(req.covered_start)
        elif req.cadence == "monthly":
            run = await runner.run_monthly(req.covered_start)
        else:
            raise HTTPException(status_code=400, detail="unknown cadence")
        return TriggerResponse(
            run_id=str(run.id),
            status=run.status,
            idempotency_key=run.idempotency_key,
        )

    @app.get("/briefs")
    async def list_briefs(cadence: str | None = None) -> list[dict[str, Any]]:
        # Placeholder - real impl would query via repositories
        return []

    return app
