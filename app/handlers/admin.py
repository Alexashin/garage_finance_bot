from __future__ import annotations

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import cancel_menu, main_menu, users_menu
from app.models import UserRole
from app.repository import Repo
from app.states import UserAdminFlow

logger = logging.getLogger(__name__)
router = Router()


def _role_from_text(t: str) -> UserRole | None:
    t = (t or "").strip().lower()
    mapping = {
        "owner": UserRole.owner,
        "viewer": UserRole.viewer,
        "worker": UserRole.worker,
        "владелец": UserRole.owner,
        "смотреть": UserRole.viewer,
        "вьювер": UserRole.viewer,
        "работяга": UserRole.worker,
        "мастер": UserRole.worker,
    }
    return mapping.get(t)


async def _is_owner(session: AsyncSession, tg_id: int) -> bool:
    repo = Repo(session)
    u = await repo.get_user_by_tg(tg_id)
    return bool(u and u.role == UserRole.owner)


@router.message(lambda m: m.text == "👥 Пользователи")
async def users_main(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_owner(session, message.from_user.id):
        await message.answer("⛔ Только владелец.", reply_markup=main_menu())
        return

    await state.clear()
    await message.answer("👥 Пользователи", reply_markup=users_menu())


@router.message(lambda m: m.text == "📋 Список")
async def users_list(message: Message, session: AsyncSession):
    if not await _is_owner(session, message.from_user.id):
        await message.answer("⛔ Только владелец.", reply_markup=main_menu())
        return

    repo = Repo(session)
    users = await repo.list_users()
    lines = ["👥 Список пользователей:"]
    for u in users:
        status = "✅" if u.is_active else "⛔"
        lines.append(f"{status} {u.telegram_id} — {u.name} ({u.role.value})")
    await message.answer("\n".join(lines), reply_markup=users_menu())


@router.message(lambda m: m.text == "📈 Добавить")
async def users_add_start(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_owner(session, message.from_user.id):
        await message.answer("⛔ Только владелец.", reply_markup=main_menu())
        return

    await state.set_state(UserAdminFlow.add_id)
    await message.answer(
        "Введите Telegram ID пользователя (число):", reply_markup=cancel_menu()
    )


@router.message(UserAdminFlow.add_id)
async def users_add_id(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_owner(session, message.from_user.id):
        await state.clear()
        await message.answer("⛔ Только владелец.", reply_markup=main_menu())
        return

    t = (message.text or "").strip()
    if not t.isdigit():
        await message.answer("Нужно число (Telegram ID).", reply_markup=cancel_menu())
        return

    await state.update_data(new_tg_id=int(t))
    await state.set_state(UserAdminFlow.add_name)
    await message.answer(
        "Имя/ник (как будет отображаться в боте):", reply_markup=cancel_menu()
    )


@router.message(UserAdminFlow.add_name)
async def users_add_name(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_owner(session, message.from_user.id):
        await state.clear()
        await message.answer("⛔ Только владелец.", reply_markup=main_menu())
        return

    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer(
            "Слишком коротко. Введите имя ещё раз.", reply_markup=cancel_menu()
        )
        return

    await state.update_data(new_name=name)
    await state.set_state(UserAdminFlow.add_role)
    await message.answer("Роль? owner / viewer / worker", reply_markup=cancel_menu())


@router.message(UserAdminFlow.add_role)
async def users_add_role(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_owner(session, message.from_user.id):
        await state.clear()
        await message.answer("⛔ Только владелец.", reply_markup=main_menu())
        return

    role = _role_from_text(message.text)
    if not role:
        await message.answer(
            "Введите роль: owner / viewer / worker", reply_markup=cancel_menu()
        )
        return

    data = await state.get_data()
    repo = Repo(session)
    existing = await repo.get_user_by_tg(int(data["new_tg_id"]))
    if existing:
        await message.answer(
            "Этот Telegram ID уже есть в базе.", reply_markup=users_menu()
        )
        await state.clear()
        return

    await repo.create_user(int(data["new_tg_id"]), data["new_name"], role)
    await state.clear()
    await message.answer("✅ Пользователь добавлен.", reply_markup=users_menu())


@router.message(lambda m: m.text == "📉 Удалить")
async def users_del_start(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_owner(session, message.from_user.id):
        await message.answer("⛔ Только владелец.", reply_markup=main_menu())
        return

    await state.set_state(UserAdminFlow.del_id)
    await message.answer(
        "Введите Telegram ID пользователя для отключения:", reply_markup=cancel_menu()
    )


@router.message(UserAdminFlow.del_id)
async def users_del_id(message: Message, session: AsyncSession, state: FSMContext):
    if not await _is_owner(session, message.from_user.id):
        await state.clear()
        await message.answer("⛔ Только владелец.", reply_markup=main_menu())
        return

    t = (message.text or "").strip()
    if not t.isdigit():
        await message.answer("Нужно число (Telegram ID).", reply_markup=cancel_menu())
        return

    repo = Repo(session)
    ok = await repo.delete_user(int(t))
    await state.clear()
    await message.answer(
        "✅ Отключен." if ok else "Не найден.", reply_markup=users_menu()
    )
