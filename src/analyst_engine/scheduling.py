"""APScheduler registration for cadence workflows.

Only the scheduler process mode registers jobs.
"""

from __future__ import annotations

import logging
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from analyst_engine.config import ProcessMode, Settings
from analyst_engine.persistence.engine import session_scope
from analyst_engine.persistence.repositories import list_topics
from analyst_engine.pipeline.daily_brief import DailyBriefPipeline
from analyst_engine.pipeline.periodic_brief import PeriodicBriefPipeline

logger = logging.getLogger(__name__)


async def register_schedules(
    scheduler: AsyncIOScheduler,
    pipeline: DailyBriefPipeline,
    weekly_pipeline: PeriodicBriefPipeline,
    monthly_pipeline: PeriodicBriefPipeline,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
) -> None:
    """Register daily, weekly, monthly jobs (idempotent by key)."""
    if settings.app_process_mode != ProcessMode.SCHEDULER:
        return

    async def _run_daily_pipeline() -> None:
        async with session_scope(session_factory) as session:
            topics = await list_topics(session)
        for topic in topics:
            try:
                await pipeline.run(date.today(), topic_id=topic.id)
            except Exception:
                logger.exception(
                    "daily pipeline failed for topic_id=%s", topic.id
                )

    async def _run_weekly_pipeline() -> None:
        # CronTrigger fires on local time; passing local date.today() (rather
        # than leaving the anchor to PeriodicBriefPipeline's default UTC
        # clock) keeps the job's window normalization aligned with the local
        # instant the job actually fired at, avoiding a wrong-day window near
        # midnight in timezones offset enough from UTC.
        async with session_scope(session_factory) as session:
            topics = await list_topics(session)
        for topic in topics:
            try:
                await weekly_pipeline.run(date.today(), topic_id=topic.id)
            except Exception:
                logger.exception(
                    "weekly pipeline failed for topic_id=%s", topic.id
                )

    async def _run_monthly_pipeline() -> None:
        async with session_scope(session_factory) as session:
            topics = await list_topics(session)
        for topic in topics:
            try:
                await monthly_pipeline.run(date.today(), topic_id=topic.id)
            except Exception:
                logger.exception(
                    "monthly pipeline failed for topic_id=%s", topic.id
                )

    # Daily at 02:00 local
    scheduler.add_job(
        _run_daily_pipeline,
        CronTrigger(hour=2, minute=0),
        id="daily-brief",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # Weekly on Sunday 03:00
    scheduler.add_job(
        _run_weekly_pipeline,
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="weekly-brief",
        replace_existing=True,
    )

    # Monthly on 1st at 04:00
    scheduler.add_job(
        _run_monthly_pipeline,
        CronTrigger(day=1, hour=4, minute=0),
        id="monthly-brief",
        replace_existing=True,
    )
