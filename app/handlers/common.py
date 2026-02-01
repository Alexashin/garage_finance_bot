from __future__ import annotations

import logging
from typing import Optional, Tuple

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import main_menu
from app.models import UserRole
from app.repository import Repo

logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")
router = Router()


ROLE_RU = {
    UserRole.owner: "Владелец",
    UserRole.worker: "Работник",
    UserRole.viewer: "Наблюдатель",
}


async def render_balance_message(repo: Repo) -> str:
    bal, reserve, available = await repo.balance()
    return (
        f"💰 Баланс: {bal} ₽\n"
        f"🔒 Резерв: {reserve} ₽\n"
        f"🟢 Доступно: {available} ₽"
    )


async def get_user_or_deny(repo: Repo, message: Message) -> Optional[object]:
    """
    Возвращает user или отправляет 'доступ запрещён' + audit лог.
    """
    tg_id = message.from_user.id
    user = await repo.get_user_by_tg(tg_id)
    if not user:
        audit.info("auth.denied | tg_id=%s | reason=no_user", tg_id)
        await message.answer("⛔ Доступ запрещён. Обратитесь к владельцу.")
        return None
    return user


def role_ru(role: UserRole) -> str:
    return ROLE_RU.get(role, str(role))


@router.message(Command("start"))
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext):
    repo = Repo(session)
    user = await get_user_or_deny(repo, message)
    if not user:
        return

    await state.clear()
    text = await render_balance_message(repo)

    audit.info(
        "ui.start | tg_id=%s | user_id=%s | role=%s",
        message.from_user.id,
        user.id,
        user.role.value,
    )
    await message.answer(
        f"Привет, {user.name}! ({role_ru(user.role)})\n\n{text}",
        reply_markup=main_menu(user.role),
    )


@router.message(Command("menu"))
async def cmd_menu(message: Message, session: AsyncSession):
    repo = Repo(session)
    user = await get_user_or_deny(repo, message)
    if not user:
        return

    text = await render_balance_message(repo)
    audit.info("ui.menu | tg_id=%s | user_id=%s", message.from_user.id, user.id)
    await message.answer(text, reply_markup=main_menu(user.role))


@router.message(lambda m: m.text == "ℹ️ Баланс")
async def show_balance(message: Message, session: AsyncSession):
    repo = Repo(session)
    user = await get_user_or_deny(repo, message)
    if not user:
        return

    text = await render_balance_message(repo)
    audit.info("balance.view | tg_id=%s | user_id=%s", message.from_user.id, user.id)
    await message.answer(text, reply_markup=main_menu(user.role))
