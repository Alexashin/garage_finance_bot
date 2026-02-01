from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserRole
from app.repository import Repo
from app.settings import Settings

logger = logging.getLogger(__name__)


def _split_csv(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


async def bootstrap_data(session: AsyncSession, settings: Settings) -> None:
    repo = Repo(session)

    # Create initial owner if users table is empty
    if await repo.count_users() == 0:
        await repo.create_user(settings.OWNER_TELEGRAM_ID, name="Owner", role=UserRole.owner)
        logger.info("Created initial owner user: %s", settings.OWNER_TELEGRAM_ID)

    # Ensure default categories
    await repo.ensure_default_categories(
        income_names=_split_csv(settings.DEFAULT_INCOME_CATEGORIES),
        expense_names=_split_csv(settings.DEFAULT_EXPENSE_CATEGORIES),
    )
