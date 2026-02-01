from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.bootstrap import bootstrap_data
from app.db import create_engine_and_session
from app.logging_config import setup_logging
from app.middlewares.db_session import DbSessionMiddleware
from app.middlewares.user import UserMiddleware
from app.settings import Settings

from app.handlers import admin, common, finance, reports

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()
    setup_logging(settings.LOG_LEVEL)

    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    engine, session_maker = create_engine_and_session(settings)

    dp.update.middleware(DbSessionMiddleware(session_maker))
    dp.update.middleware(UserMiddleware())

    # Routers
    dp.include_router(common.router)
    dp.include_router(finance.router)
    dp.include_router(reports.router)
    dp.include_router(admin.router)

    # Bootstrap DB data on startup
    async with session_maker() as session:
        await bootstrap_data(session, settings)
        await session.commit()

    logger.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
