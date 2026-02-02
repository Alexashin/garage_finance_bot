from __future__ import annotations

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import cancel_menu, users_menu
from app.models import User, UserRole
from app.repository import Repo
from app.states import UserAdminFlow
from app.models import CategoryKind
from app.states import CategoryAdminFlow
from app.utils.guards import require_owner, require_owner_callback

logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")
router = Router()


ROLE_RU = {
    UserRole.owner: "Владелец",
    UserRole.viewer: "Наблюдатель",
    UserRole.worker: "Работник",
}

KIND_RU = {
    CategoryKind.income: "Доходы",
    CategoryKind.expense: "Расходы",
}


def role_ru(role: UserRole) -> str:
    return ROLE_RU.get(role, role.value)


def kind_ru(k: CategoryKind) -> str:
    return KIND_RU.get(k, k.value)


# async def _is_owner(session: AsyncSession, tg_id: int) -> bool:
#     repo = Repo(session)
#     u = await repo.get_user_by_tg(tg_id)
#     return bool(u and u.role == UserRole.owner)


def roles_inline_kb(prefix: str = "role") -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="Владелец", callback_data=f"{prefix}:owner")
    kb.button(text="Работник", callback_data=f"{prefix}:worker")
    kb.button(text="Наблюдатель", callback_data=f"{prefix}:viewer")
    kb.adjust(1)
    return kb


def categories_kind_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Доходы", callback_data="catkind:income")
    kb.button(text="📤 Расходы", callback_data="catkind:expense")
    kb.adjust(1)
    return kb


def categories_list_kb(kind: CategoryKind, cats: list) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for c in cats:
        kb.button(text=f"• {c.name}", callback_data=f"catpick:{c.id}")
    kb.button(text="➕ Добавить", callback_data=f"catadd:{kind.value}")
    kb.button(text="⬅️ Назад", callback_data="catback:kinds")
    kb.adjust(1)
    return kb


def category_actions_kb(category_id: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Переименовать", callback_data=f"catrename:{category_id}")
    kb.button(text="🗑 Удалить", callback_data=f"catdel:{category_id}")
    kb.button(text="⬅️ К списку", callback_data="catback:list")
    kb.adjust(1)
    return kb


@router.message(lambda m: m.text == "👥 Пользователи")
async def users_main(message: Message, state: FSMContext, user: User | None):
    if not await require_owner(message, user, action="users_main"):
        return
    await state.clear()
    await message.answer("👥 Пользователи", reply_markup=users_menu())


@router.message(lambda m: m.text == "📋 Список")
async def users_list(message: Message, session: AsyncSession, user: User | None):
    if not await require_owner(message, user, action="users_list"):
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
async def users_add_start(message: Message, state: FSMContext, user: User | None):
    if not await require_owner(message, user, action="users_add_start"):
        return

    await state.set_state(UserAdminFlow.add_id)
    await message.answer(
        "Введите Telegram ID пользователя (число):", reply_markup=cancel_menu()
    )


@router.message(UserAdminFlow.add_id)
async def users_add_id(message: Message, state: FSMContext, user: User | None):
    if not await require_owner(message, user, action="users_add_id"):
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
async def users_add_name(message: Message, state: FSMContext, user: User | None):
    if not await require_owner(message, user, action="users_add_name"):
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
    if not await require_owner_callback(callback, user, action="users_add_role_cb"):
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
async def users_del_start(message: Message, state: FSMContext, user: User | None):
    if not await require_owner(message, user, action="users_del_start"):
        return

    await state.set_state(UserAdminFlow.del_id)
    await message.answer(
        "Введите Telegram ID пользователя для отключения:", reply_markup=cancel_menu()
    )


@router.message(UserAdminFlow.del_id)
async def users_del_id(
    message: Message, session: AsyncSession, state: FSMContext, user
):
    if not await require_owner(message, user, action="users_del_id"):
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


@router.message(lambda m: m.text == "🗂 Категории")
async def categories_main(message: Message, state: FSMContext, user: User | None):
    if not await require_owner(message, user, action="categories_main"):
        return

    await state.clear()
    await message.answer(
        "🗂 Управление категориями. Выбери тип:",
        reply_markup=categories_kind_kb().as_markup(),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("catkind:"))
async def categories_choose_kind(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, user
):
    if not await require_owner_callback(
        callback, user, action="categories_choose_kind"
    ):
        return

    raw = callback.data.split(":", 1)[1]
    kind = CategoryKind.income if raw == "income" else CategoryKind.expense

    await state.update_data(cat_kind=kind.value)

    repo = Repo(session)
    cats = await repo.list_categories(kind)

    await callback.message.edit_text(
        f"🗂 Категории: *{kind_ru(kind)}*\nВыбери категорию или добавь новую:",
        reply_markup=categories_list_kb(kind, cats).as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("catadd:"))
async def categories_add_start(
    callback: CallbackQuery, state: FSMContext, user: User | None
):
    if not await require_owner_callback(callback, user, action="categories_add_start"):
        return

    kind_raw = callback.data.split(":", 1)[1]
    await state.update_data(cat_kind=kind_raw)
    await state.set_state(CategoryAdminFlow.add_name)

    await callback.message.answer(
        "Введите название новой категории (2–64 символа):",
        reply_markup=cancel_menu(),
    )
    await callback.answer()


@router.message(CategoryAdminFlow.add_name)
async def categories_add_name(
    message: Message, session: AsyncSession, state: FSMContext, user
):
    if not await require_owner(message, user, action="categories_add_name"):
        await state.clear()
        return

    name = (message.text or "").strip()
    if len(name) < 2 or len(name) > 64:
        await message.answer(
            "Название должно быть 2–64 символа. Введите ещё раз:",
            reply_markup=cancel_menu(),
        )
        return

    data = await state.get_data()
    kind = CategoryKind(data["cat_kind"])

    repo = Repo(session)
    cat = await repo.create_category(kind, name)

    audit.info(
        "category.created | owner_tg=%s | kind=%s | name=%s | id=%s",
        message.from_user.id,
        kind.value,
        cat.name,
        cat.id,
    )

    await state.clear()

    cats = await repo.list_categories(kind)
    await message.answer(
        f"✅ Категория добавлена: {cat.name}\n\n🗂 Категории: {kind_ru(kind)}",
        reply_markup=categories_list_kb(kind, cats).as_markup(),
    )


@router.callback_query(lambda c: c.data and c.data.startswith("catpick:"))
async def categories_pick(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, user
):
    if not await require_owner_callback(callback, user, action="categories_pick"):
        return

    cat_id = int(callback.data.split(":", 1)[1])

    repo = Repo(session)
    cat = await repo.get_category(cat_id)
    if not cat or not cat.is_active:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    await state.update_data(cat_kind=cat.kind.value, cat_id=cat.id)

    await callback.message.edit_text(
        f"🗂 Категория: *{cat.name}*\nТип: *{kind_ru(cat.kind)}*",
        reply_markup=category_actions_kb(cat.id).as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("catrename:"))
async def categories_rename_start(
    callback: CallbackQuery, state: FSMContext, user: User | None
):
    if not await require_owner_callback(
        callback, user, action="categories_rename_start"
    ):
        return

    cat_id = int(callback.data.split(":", 1)[1])
    await state.update_data(cat_id=cat_id)
    await state.set_state(CategoryAdminFlow.rename_name)

    await callback.message.answer(
        "Введите новое название категории:", reply_markup=cancel_menu()
    )
    await callback.answer()


@router.message(CategoryAdminFlow.rename_name)
async def categories_rename_apply(
    message: Message, session: AsyncSession, state: FSMContext, user
):
    if not await require_owner(message, user, action="categories_rename_apply"):
        await state.clear()
        return

    new_name = (message.text or "").strip()
    data = await state.get_data()
    cat_id = int(data["cat_id"])

    repo = Repo(session)
    ok, msg = await repo.rename_category(cat_id, new_name)

    if not ok:
        await message.answer(msg, reply_markup=cancel_menu())
        return

    audit.info(
        "category.renamed | owner_tg=%s | cat_id=%s | new_name=%s",
        message.from_user.id,
        cat_id,
        new_name,
    )

    cat = await repo.get_category(cat_id)
    kind = cat.kind if cat else CategoryKind.income
    cats = await repo.list_categories(kind)

    await state.clear()
    await message.answer(msg, reply_markup=categories_list_kb(kind, cats).as_markup())


@router.callback_query(lambda c: c.data and c.data.startswith("catdel:"))
async def categories_delete(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, user
):
    if not await require_owner_callback(callback, user, action="categories_delete"):
        return

    cat_id = int(callback.data.split(":", 1)[1])
    repo = Repo(session)
    ok, msg = await repo.deactivate_category(cat_id)

    if not ok:
        await callback.answer(msg, show_alert=True)
        return

    audit.info(
        "category.deleted | owner_tg=%s | cat_id=%s", callback.from_user.id, cat_id
    )

    cat = await repo.get_category(cat_id)  # может быть уже не активна, но kind остаётся
    kind_raw = (await state.get_data()).get("cat_kind")
    kind = (
        CategoryKind(kind_raw)
        if kind_raw
        else (cat.kind if cat else CategoryKind.income)
    )

    cats = await repo.list_categories(kind)

    await callback.message.edit_text(
        f"🗂 Категории: *{kind_ru(kind)}*",
        reply_markup=categories_list_kb(kind, cats).as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer("Удалено.")


@router.callback_query(lambda c: c.data == "catback:kinds")
async def categories_back_kinds(
    callback: CallbackQuery, state: FSMContext, user: User | None
):
    if not await require_owner_callback(callback, user, action="categories_back_kinds"):
        return

    await state.clear()
    await callback.message.edit_text(
        "🗂 Управление категориями. Выбери тип:",
        reply_markup=categories_kind_kb().as_markup(),
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "catback:list")
async def categories_back_list(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, user
):
    if not await require_owner_callback(callback, user, action="categories_back_list"):
        return

    data = await state.get_data()
    kind = CategoryKind(data.get("cat_kind", "income"))

    repo = Repo(session)
    cats = await repo.list_categories(kind)

    await callback.message.edit_text(
        f"🗂 Категории: *{kind_ru(kind)}*",
        reply_markup=categories_list_kb(kind, cats).as_markup(),
        parse_mode="Markdown",
    )
    await callback.answer()
