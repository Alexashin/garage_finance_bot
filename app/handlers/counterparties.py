import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.repository import Repo
from app.keyboards import main_menu, cancel_menu
from app.states import CounterpartyFlow
from app.utils.guards import require_owner, require_owner_callback

audit = logging.getLogger("audit")
router = Router()


def cp_menu_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Список", callback_data="cp:list")
    kb.button(text="🔍 Поиск", callback_data="cp:search")
    kb.button(text="➕ Добавить", callback_data="cp:add")
    kb.adjust(1)
    return kb


def cp_list_kb(items) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for cp in items[:30]:
        kb.button(text=cp.name, callback_data=f"cp:open:{cp.id}")
    kb.button(text="⬅️ Назад", callback_data="cp:back")
    kb.adjust(1)
    return kb


def cp_card_kb(cp_id: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Имя", callback_data=f"cp:edit_name:{cp_id}")
    kb.button(text="📝 Комментарий", callback_data=f"cp:edit_comment:{cp_id}")
    kb.button(text="🙈 Скрыть", callback_data=f"cp:hide:{cp_id}")
    kb.button(text="⬅️ Назад", callback_data="cp:list")
    kb.adjust(1)
    return kb


@router.message(lambda m: m.text == "🏢 Контрагенты")
async def cp_main(
    message: Message, session: AsyncSession, state: FSMContext, user: User | None
):
    repo = Repo(session)
    if not await require_owner(message, user, action="cp_main"):
        return

    await state.clear()
    await message.answer("🏢 Контрагенты", reply_markup=cp_menu_kb().as_markup())
    audit.info("cp.open_menu | tg_id=%s | user_id=%s", message.from_user.id, user.id)


@router.callback_query(lambda c: c.data == "cp:back")
async def cp_back(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, user: User | None
):
    if not await require_owner_callback(callback, user, action="cp_back"):
        return
    await state.clear()
    await callback.message.answer(
        "🏢 Контрагенты", reply_markup=cp_menu_kb().as_markup()
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "cp:list")
async def cp_list(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, user: User | None
):
    if not await require_owner_callback(callback, user, action="cp_list"):
        return
    repo = Repo(session)
    await state.clear()

    items = await repo.list_counterparties(active_only=True)
    if not items:
        await callback.message.answer(
            "Контрагентов пока нет.", reply_markup=cp_menu_kb().as_markup()
        )
        await callback.answer()
        return

    await callback.message.answer(
        "📋 Контрагенты:", reply_markup=cp_list_kb(items).as_markup()
    )
    audit.info("cp.list | tg_id=%s | count=%s", callback.from_user.id, len(items))
    await callback.answer()


@router.callback_query(lambda c: c.data == "cp:search")
async def cp_search_start(
    callback: CallbackQuery, state: FSMContext, user: User | None
):
    if not await require_owner_callback(callback, user, action="cp_search_start"):
        return
    await state.set_state(CounterpartyFlow.search)
    await callback.message.answer(
        "Введите часть названия для поиска:", reply_markup=cancel_menu()
    )
    await callback.answer()


@router.message(CounterpartyFlow.search)
async def cp_search_do(
    message: Message, session: AsyncSession, state: FSMContext, user: User | None
):
    repo = Repo(session)
    if not await require_owner(message, user, action="cp_search_do"):
        return

    q = (message.text or "").strip()
    if len(q) < 2:
        await message.answer("Введите минимум 2 символа.")
        return

    items = await repo.search_counterparties(q, active_only=True)
    await state.clear()

    if not items:
        await message.answer(
            "Ничего не найдено.", reply_markup=cp_menu_kb().as_markup()
        )
        return

    await message.answer(
        "Результаты поиска:", reply_markup=cp_list_kb(items).as_markup()
    )
    audit.info(
        "cp.search | tg_id=%s | q=%s | count=%s", message.from_user.id, q, len(items)
    )


@router.callback_query(lambda c: c.data == "cp:add")
async def cp_add_start(callback: CallbackQuery, state: FSMContext, user: User | None):
    if not await require_owner_callback(callback, user, action="cp_add_start"):
        return
    await state.set_state(CounterpartyFlow.add_name)
    await callback.message.answer(
        "Введите название контрагента:", reply_markup=cancel_menu()
    )
    await callback.answer()


@router.message(CounterpartyFlow.add_name)
async def cp_add_name(message: Message, state: FSMContext, user: User | None):
    if not await require_owner(message, user, action="cp_add_name"):
        return
    name = " ".join((message.text or "").split())
    if len(name) < 2:
        await message.answer("Слишком коротко. Введите название ещё раз.")
        return
    await state.update_data(cp_name=name)
    await state.set_state(CounterpartyFlow.add_comment)
    await message.answer(
        "Комментарий (можно '-' если не нужен):", reply_markup=cancel_menu()
    )


@router.message(CounterpartyFlow.add_comment)
async def cp_add_finish(
    message: Message, session: AsyncSession, state: FSMContext, user: User | None
):
    repo = Repo(session)
    if not await require_owner(message, user, action="cp_add_finish"):
        return

    data = await state.get_data()
    name = data.get("cp_name")
    comment = (message.text or "").strip()
    if comment == "-" or comment == "—":
        comment = ""

    cp = await repo.create_counterparty(name=name, comment=comment)
    await state.clear()

    await message.answer(
        f"✅ Добавлено: {cp.name}\nКомментарий: {cp.comment or '—'}",
        reply_markup=cp_menu_kb().as_markup(),
    )
    audit.info(
        "cp.create | tg_id=%s | cp_id=%s | name=%s",
        message.from_user.id,
        cp.id,
        cp.name,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cp:open:"))
async def cp_open(callback: CallbackQuery, session: AsyncSession, user: User | None):
    repo = Repo(session)
    if not await require_owner_callback(callback, user, action="cp_open"):
        return
    cp_id = int(callback.data.split(":")[-1])
    cp = await repo.get_counterparty(cp_id)
    if not cp or not cp.is_active:
        await callback.answer("Не найдено.", show_alert=True)
        return

    text = f"🏢 Контрагент\n\n**{cp.name}**\nКомментарий: {cp.comment or '—'}"
    await callback.message.answer(
        text, reply_markup=cp_card_kb(cp.id).as_markup(), parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("cp:edit_name:"))
async def cp_edit_name_start(
    callback: CallbackQuery, state: FSMContext, user: User | None
):
    if not await require_owner_callback(callback, user, action="cp_edit_name_start"):
        return
    cp_id = int(callback.data.split(":")[-1])
    await state.update_data(cp_edit_id=cp_id)
    await state.set_state(CounterpartyFlow.edit_name)
    await callback.message.answer("Введите новое название:", reply_markup=cancel_menu())
    await callback.answer()


@router.message(CounterpartyFlow.edit_name)
async def cp_edit_name_finish(
    message: Message, session: AsyncSession, state: FSMContext, user: User | None
):
    repo = Repo(session)
    if not await require_owner(message, user, action="cp_edit_name_finish"):
        return

    data = await state.get_data()
    cp_id = int(data.get("cp_edit_id"))
    name = " ".join((message.text or "").split())

    ok, msg = await repo.update_counterparty(cp_id, name=name)
    await state.clear()
    await message.answer(msg, reply_markup=cp_menu_kb().as_markup())
    audit.info(
        "cp.edit_name | tg_id=%s | cp_id=%s | ok=%s", message.from_user.id, cp_id, ok
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cp:edit_comment:"))
async def cp_edit_comment_start(
    callback: CallbackQuery, state: FSMContext, user: User | None
):
    if not await require_owner_callback(callback, user, action="cp_edit_comment_start"):
        return
    cp_id = int(callback.data.split(":")[-1])
    await state.update_data(cp_edit_id=cp_id)
    await state.set_state(CounterpartyFlow.edit_comment)
    await callback.message.answer(
        "Введите новый комментарий (или '-' чтобы очистить):",
        reply_markup=cancel_menu(),
    )
    await callback.answer()


@router.message(CounterpartyFlow.edit_comment)
async def cp_edit_comment_finish(
    message: Message, session: AsyncSession, state: FSMContext, user: User | None
):
    repo = Repo(session)
    if not await require_owner(message, user, action="cp_edit_comment_finish"):
        return

    data = await state.get_data()
    cp_id = int(data.get("cp_edit_id"))
    comment = (message.text or "").strip()
    if comment in ("-", "—"):
        comment = ""

    ok, msg = await repo.update_counterparty(cp_id, comment=comment)
    await state.clear()
    await message.answer(msg, reply_markup=cp_menu_kb().as_markup())
    audit.info(
        "cp.edit_comment | tg_id=%s | cp_id=%s | ok=%s", message.from_user.id, cp_id, ok
    )


@router.callback_query(lambda c: c.data and c.data.startswith("cp:hide:"))
async def cp_hide(callback: CallbackQuery, session: AsyncSession, user: User | None):
    repo = Repo(session)
    if not await require_owner_callback(callback, user, action="cp_hide"):
        return
    cp_id = int(callback.data.split(":")[-1])

    ok, msg = await repo.deactivate_counterparty(cp_id)
    await callback.message.answer(msg, reply_markup=cp_menu_kb().as_markup())
    audit.info(
        "cp.hide | tg_id=%s | cp_id=%s | ok=%s", callback.from_user.id, cp_id, ok
    )
    await callback.answer()
