from __future__ import annotations

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import cancel_menu, main_menu, users_menu
from app.models import UserRole
from app.repository import Repo
from app.states import UserAdminFlow

logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")
router = Router()


ROLE_RU = {
    UserRole.owner: "Владелец",
    UserRole.viewer: "Наблюдатель",
    UserRole.worker: "Работник",
}


def role_ru(role: UserRole) -> str:
    return ROLE_RU.get(role, role.value)


async def _is_owner(session: AsyncSession, tg_id: int) -> bool:
    repo = Repo(session)
    u = await repo.get_user_by_tg(tg_id)
    return bool(u and u.role == UserRole.owner)


def roles_inline_kb(prefix: str = "role") -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="Владелец", callback_data=f"{prefix}:owner")
    kb.button(text="Работник", callback_data=f"{prefix}:worker")
    kb.button(text="Наблюдатель", callback_data=f"{prefix}:viewer")
    kb.adjust(1)
    return kb


@router.message(lambda m: m.text == "👥 Пользователи")
async def users_main(message: Message, session: AsyncSession, state: FSMContext, user):
    if not await _is_owner(session, message.from_user.id):
        audit.info("auth.denied | tg_id=%s | action=users_main", message.from_user.id)
        await message.answer("⛔ Только владелец.", reply_markup=main_menu(user.role))
        return

    await state.clear()
    await message.answer("👥 Пользователи", reply_markup=users_menu())


@router.message(lambda m: m.text == "📋 Список")
async def users_list(message: Message, session: AsyncSession, user):
    if not await _is_owner(session, message.from_user.id):
        audit.info("auth.denied | tg_id=%s | action=users_list", message.from_user.id)
        await message.answer("⛔ Только владелец.", reply_markup=main_menu(user.role))
        return

    repo = Repo(session)
    users = await repo.list_users()
    lines = ["👥 Список пользователей:"]
    for u in users:
        status = "✅" if u.is_active else "⛔"
        lines.append(f"{status} {u.telegram_id} — {u.name} ({role_ru(u.role)})")

    audit.info("users.list | tg_id=%s | count=%s", message.from_user.id, len(users))
    await message.answer("\n".join(lines), reply_markup=users_menu())


@router.message(lambda m: m.text == "🟢 Добавить")
async def users_add_start(
    message: Message, session: AsyncSession, state: FSMContext, user
):
    if not await _is_owner(session, message.from_user.id):
        audit.info(
            "auth.denied | tg_id=%s | action=users_add_start", message.from_user.id
        )
        await message.answer("⛔ Только владелец.", reply_markup=main_menu(user.role))
        return

    await state.set_state(UserAdminFlow.add_id)
    await message.answer(
        "Введите Telegram ID пользователя (число):", reply_markup=cancel_menu()
    )


@router.message(UserAdminFlow.add_id)
async def users_add_id(
    message: Message, session: AsyncSession, state: FSMContext, user
):
    if not await _is_owner(session, message.from_user.id):
        await state.clear()
        audit.info("auth.denied | tg_id=%s | action=users_add_id", message.from_user.id)
        await message.answer("⛔ Только владелец.", reply_markup=main_menu(user.role))
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
async def users_add_name(
    message: Message, session: AsyncSession, state: FSMContext, user
):
    if not await _is_owner(session, message.from_user.id):
        await state.clear()
        audit.info(
            "auth.denied | tg_id=%s | action=users_add_name", message.from_user.id
        )
        await message.answer("⛔ Только владелец.", reply_markup=main_menu(user.role))
        return

    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer(
            "Слишком коротко. Введите имя ещё раз.", reply_markup=cancel_menu()
        )
        return

    await state.update_data(new_name=name)
    await state.set_state(UserAdminFlow.add_role)

    kb = roles_inline_kb(prefix="user_add_role").as_markup()
    await message.answer("Выберите роль кнопкой:", reply_markup=kb)


@router.callback_query(
    lambda c: c.data and c.data.startswith("user_add_role:"), UserAdminFlow.add_role
)
async def users_add_role_cb(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, user
):
    if not await _is_owner(session, callback.from_user.id):
        await state.clear()
        audit.info(
            "auth.denied | tg_id=%s | action=users_add_role_cb", callback.from_user.id
        )
        await callback.message.answer(
            "⛔ Только владелец.", reply_markup=main_menu(user.role)
        )
        await callback.answer()
        return

    raw = callback.data.split(":", 1)[1]
    role_map = {
        "owner": UserRole.owner,
        "worker": UserRole.worker,
        "viewer": UserRole.viewer,
    }
    role = role_map.get(raw)
    if not role:
        await callback.answer("Не понял роль.", show_alert=True)
        return

    data = await state.get_data()
    repo = Repo(session)

    new_tg_id = int(data["new_tg_id"])
    existing = await repo.get_user_by_tg(new_tg_id)
    if existing:
        await callback.message.answer(
            "Этот Telegram ID уже есть в базе.", reply_markup=users_menu()
        )
        await state.clear()
        await callback.answer()
        return

    await repo.create_user(new_tg_id, data["new_name"], role)
    audit.info(
        "user.created | owner_tg=%s | new_tg=%s | role=%s",
        callback.from_user.id,
        new_tg_id,
        role.value,
    )

    await state.clear()
    await callback.message.answer(
        "✅ Пользователь добавлен.", reply_markup=users_menu()
    )
    await callback.answer()


@router.message(lambda m: m.text == "🔴 Удалить")
async def users_del_start(
    message: Message, session: AsyncSession, state: FSMContext, user
):
    if not await _is_owner(session, message.from_user.id):
        audit.info(
            "auth.denied | tg_id=%s | action=users_del_start", message.from_user.id
        )
        await message.answer("⛔ Только владелец.", reply_markup=main_menu(user.role))
        return

    await state.set_state(UserAdminFlow.del_id)
    await message.answer(
        "Введите Telegram ID пользователя для отключения:", reply_markup=cancel_menu()
    )


@router.message(UserAdminFlow.del_id)
async def users_del_id(
    message: Message, session: AsyncSession, state: FSMContext, user
):
    if not await _is_owner(session, message.from_user.id):
        await state.clear()
        audit.info("auth.denied | tg_id=%s | action=users_del_id", message.from_user.id)
        await message.answer("⛔ Только владелец.", reply_markup=main_menu(user.role))
        return

    t = (message.text or "").strip()
    if not t.isdigit():
        await message.answer("Нужно число (Telegram ID).", reply_markup=cancel_menu())
        return

    repo = Repo(session)
    ok = await repo.delete_user(int(t))
    audit.info(
        "user.deleted | owner_tg=%s | target_tg=%s | ok=%s", message.from_user.id, t, ok
    )

    await state.clear()
    await message.answer(
        "✅ Отключен." if ok else "Не найден.", reply_markup=users_menu()
    )
