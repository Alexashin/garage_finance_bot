from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import main_menu
from app.repository import Repo

logger = logging.getLogger(__name__)
router = Router()


async def render_balance_message(repo: Repo) -> str:
    bal, reserve, available = await repo.balance()
    return (
        f"💰 Баланс: {bal} ₽\n"
        f"🔒 Резерв: {reserve} ₽\n"
        f"🟢 Доступно: {available} ₽"
    )


@router.message(Command("start"))
async def cmd_start(message: Message, session: AsyncSession, state: FSMContext):
    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer("⛔ Доступ запрещён. Обратитесь к владельцу.")
        return

    await state.clear()
    text = await render_balance_message(repo)
    await message.answer(f"Привет, {user.name}!\n\n" + text, reply_markup=main_menu())


@router.message(Command("menu"))
async def cmd_menu(message: Message, session: AsyncSession):
    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer("⛔ Доступ запрещён.")
        return
    text = await render_balance_message(repo)
    await message.answer(text, reply_markup=main_menu())


@router.message(lambda m: m.text == "ℹ️ Баланс")
async def show_balance(message: Message, session: AsyncSession):
    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer("⛔ Доступ запрещён.")
        return
    text = await render_balance_message(repo)
    await message.answer(text, reply_markup=main_menu())
