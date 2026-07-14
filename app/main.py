"""Application entrypoint: validate config, DB, scheduler, polling, shutdown."""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncEngine

from app.bot import create_bot, create_dispatcher
from app.config import get_settings
from app.database.engine import create_engine, create_session_factory
from app.logging_setup import setup_logging
from app.models import Base
from app.scheduler.setup import create_scheduler

logger = logging.getLogger(__name__)


async def init_db(engine: AsyncEngine) -> None:
    """Create tables if missing (Alembic is preferred for schema evolution)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema is ready")


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    await init_db(engine)

    bot = create_bot(settings)
    dispatcher = create_dispatcher(settings, session_factory)
    scheduler = create_scheduler(
        bot,
        session_factory,
        interval_minutes=settings.scheduler_interval_minutes,
    )

    logger.info("Starting scheduler and polling…")
    scheduler.start()
    try:
        await dispatcher.start_polling(bot)
    finally:
        logger.info("Shutting down…")
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await engine.dispose()
        logger.info("Shutdown complete")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Interrupted by user")


if __name__ == "__main__":
    main()
