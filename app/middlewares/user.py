from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.repository import Repo


class UserMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        session: AsyncSession = data["session"]  # у тебя уже есть DI сессии
        tg_user = data.get("event_from_user")
        if tg_user:
            repo = Repo(session)
            data["user"] = await repo.get_user_by_tg(tg_user.id)
        else:
            data["user"] = None
        return await handler(event, data)
