"""APScheduler registration for cadence workflows.

Only the scheduler process mode registers jobs.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from analyst_engine.config import ProcessMode, Settings
from analyst_engine.workflows.runner import WorkflowRunner  # defined later in Task 5/6


async def register_schedules(
    scheduler: AsyncIOScheduler,
    runner: WorkflowRunner,
    settings: Settings,
) -> None:
    """Register daily, weekly, monthly jobs (idempotent by key)."""
    if settings.app_process_mode != ProcessMode.SCHEDULER:
        return

    # Daily at 02:00 local
    scheduler.add_job(
        runner.run_daily,
        CronTrigger(hour=2, minute=0),
        id="daily-brief",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Weekly on Sunday 03:00
    scheduler.add_job(
        runner.run_weekly,
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="weekly-brief",
        replace_existing=True,
    )

    # Monthly on 1st at 04:00
    scheduler.add_job(
        runner.run_monthly,
        CronTrigger(day=1, hour=4, minute=0),
        id="monthly-brief",
        replace_existing=True,
    )
