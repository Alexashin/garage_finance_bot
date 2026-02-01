from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.repository import Repo
from app.models import UserRole


class IsAuthed(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, session: AsyncSession) -> bool:
        tg_id = event.from_user.id
        repo = Repo(session)
        user = await repo.get_user_by_tg(tg_id)
        return user is not None


class RoleAtLeast(BaseFilter):
    """Simple role gating.

    owner: can do everything
    viewer: can view
    worker: can add income/expense/reserve

    We implement as allowed_roles set.
    """

    def __init__(self, *roles: UserRole):
        self.allowed_roles = set(roles)

    async def __call__(self, event: Message | CallbackQuery, session: AsyncSession) -> bool:
        repo = Repo(session)
        user = await repo.get_user_by_tg(event.from_user.id)
        if not user:
            return False
        if user.role == UserRole.owner:
            return True
        return user.role in self.allowed_roles
