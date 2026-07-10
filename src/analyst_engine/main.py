"""Entry point for api (uvicorn) or scheduler mode."""

import asyncio
import os

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from analyst_engine.config import ProcessMode, Settings
from analyst_engine.scheduling import register_schedules
from analyst_engine.workflows.runner import WorkflowRunner


def run_api() -> None:
    settings = Settings()
    uvicorn.run(
        "analyst_engine.api.app:create_app",
        host="0.0.0.0",
        port=8000,
        factory=True,
        reload=False,
    )


async def run_scheduler() -> None:
    settings = Settings()
    # Minimal wiring (real version would also create gateway + checkpointer)
    runner = WorkflowRunner(settings, None, None, None)  # type: ignore[arg-type]
    scheduler = AsyncIOScheduler()
    await register_schedules(scheduler, runner, settings)
    scheduler.start()
    # Keep process alive
    try:
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    mode = os.getenv("APP_PROCESS_MODE", "api")
    if mode == ProcessMode.SCHEDULER:
        asyncio.run(run_scheduler())
    else:
        run_api()
