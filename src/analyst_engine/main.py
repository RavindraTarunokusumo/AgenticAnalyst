"""Entry point for api (uvicorn) or scheduler mode."""

import asyncio
import os
from collections.abc import Awaitable, Callable

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from analyst_engine.config import ProcessMode, Settings
from analyst_engine.pipeline.daily_brief import DailyBriefPipeline
from analyst_engine.runtime import (
    RuntimeDependencies,
    build_daily_brief_pipeline,
    build_ingestion_service,
    create_runtime,
)
from analyst_engine.scheduling import register_schedules
from analyst_engine.workflows.runner import WorkflowRunner


def run_api() -> None:
    uvicorn.run(
        "analyst_engine.api.app:create_app",
        host="0.0.0.0",
        port=8000,
        factory=True,
        reload=False,
    )


async def _wait_forever() -> None:
    await asyncio.Event().wait()


async def run_scheduler(
    *,
    settings_factory: Callable[[], Settings] = Settings,
    runtime_factory: Callable[[Settings], Awaitable[RuntimeDependencies]] = create_runtime,
    scheduler_factory: Callable[[], AsyncIOScheduler] = AsyncIOScheduler,
    schedule_registrar: Callable[
        [AsyncIOScheduler, WorkflowRunner, DailyBriefPipeline, Settings], Awaitable[None]
    ] = register_schedules,
    wait_forever: Callable[[], Awaitable[None]] = _wait_forever,
) -> None:
    settings = settings_factory()
    runtime = await runtime_factory(settings)
    scheduler: AsyncIOScheduler | None = None
    started = False
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
        scheduler = scheduler_factory()
        await schedule_registrar(scheduler, runner, pipeline, settings)
        scheduler.start()
        started = True
        await wait_forever()
    finally:
        try:
            if scheduler is not None and started:
                scheduler.shutdown()
        finally:
            await runtime.close()


if __name__ == "__main__":
    mode = os.getenv("APP_PROCESS_MODE", "api")
    if mode == ProcessMode.SCHEDULER:
        asyncio.run(run_scheduler())
    else:
        run_api()
