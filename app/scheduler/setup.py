"""Scheduler setup."""

from __future__ import annotations

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.scheduler.jobs import process_debt_review_job, process_reminders_job

logger = logging.getLogger(__name__)


def create_scheduler(
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    interval_minutes: int,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        process_reminders_job,
        trigger="interval",
        minutes=interval_minutes,
        kwargs={"bot": bot, "session_factory": session_factory},
        id="subscription_reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        process_debt_review_job,
        trigger="interval",
        minutes=interval_minutes,
        kwargs={"bot": bot, "session_factory": session_factory},
        id="debt_review_reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("Scheduler configured: every %s minutes", interval_minutes)
    return scheduler
