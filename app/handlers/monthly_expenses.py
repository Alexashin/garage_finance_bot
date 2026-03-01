from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, KeyboardButton, Message, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import cancel_menu, main_menu
from app.models import CategoryKind, OperationType, User
from app.repository import Repo
from app.states import MonthlyExpenseFlow
from app.utils.guards import require_owner, require_owner_callback
from app.utils.money import parse_amount

logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")
router = Router()

MSK = ZoneInfo("Europe/Moscow")


# ---------- keyboards ----------
def me_menu_kb() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="📋 Список", callback_data="me:list")
    kb.button(text="➕ Добавить", callback_data="me:add")
    kb.button(text="🧾 Списать за текущий месяц", callback_data="me:apply")
    kb.button(text="⬅️ В меню", callback_data="me:back_menu")
    kb.adjust(1)
    return kb


def me_list_kb(items) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    for me in items[:30]:
        kb.button(text=f"{me.day_of_month:02d} — {me.title}", callback_data=f"me:open:{me.id}")
    kb.button(text="⬅️ Назад", callback_data="me:back")
    kb.adjust(1)
    return kb


def me_card_kb(me_id: int) -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🙈 Скрыть", callback_data=f"me:hide:{me_id}")
    kb.button(text="⬅️ Назад", callback_data="me:list")
    kb.adjust(1)
    return kb


def categories_kb(names: list[str]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="— Без категории")]]
    rows += [[KeyboardButton(text=n)] for n in names]
    rows.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def counterparties_kb(names: list[str]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="— Без контрагента")]]
    rows += [[KeyboardButton(text=n)] for n in names]
    rows.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


# ---------- entry ----------
@router.message(lambda m: m.text == "📅 Ежемесячные траты")
async def me_main(message: Message, state: FSMContext, user: User | None):
    if not await require_owner(message, user, action="me_main"):
        return
    await state.clear()
    await message.answer("📅 Ежемесячные траты", reply_markup=me_menu_kb().as_markup())
    audit.info("me.open_menu | tg_id=%s | user_id=%s", message.from_user.id, user.id)


@router.callback_query(lambda c: c.data == "me:back_menu")
async def me_back_menu(callback: CallbackQuery, state: FSMContext, user: User | None):
    if not await require_owner_callback(callback, user, action="me_back_menu"):
        return
    await state.clear()
    await callback.message.answer("Ок.", reply_markup=main_menu(user.role))
    await callback.answer()


@router.callback_query(lambda c: c.data == "me:back")
async def me_back(callback: CallbackQuery, state: FSMContext, user: User | None):
    if not await require_owner_callback(callback, user, action="me_back"):
        return
    await state.clear()
    await callback.message.answer("📅 Ежемесячные траты", reply_markup=me_menu_kb().as_markup())
    await callback.answer()


# ---------- list / open / hide ----------
@router.callback_query(lambda c: c.data == "me:list")
async def me_list(callback: CallbackQuery, session: AsyncSession, state: FSMContext, user: User | None):
    if not await require_owner_callback(callback, user, action="me_list"):
        return
    await state.clear()
    repo = Repo(session)
    items = await repo.list_monthly_expenses(active_only=True)
    if not items:
        await callback.message.answer("Пока пусто.", reply_markup=me_menu_kb().as_markup())
        await callback.answer()
        return
    await callback.message.answer("📋 Шаблоны:", reply_markup=me_list_kb(items).as_markup())
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("me:open:"))
async def me_open(callback: CallbackQuery, session: AsyncSession, user: User | None):
    if not await require_owner_callback(callback, user, action="me_open"):
        return
    me_id = int(callback.data.split(":")[-1])
    repo = Repo(session)
    me = await repo.get_monthly_expense(me_id)
    if not me or not me.is_active:
        await callback.answer("Не найдено.", show_alert=True)
        return

    cat_name = me.category.name if getattr(me, "category", None) else "—"
    cp_name = me.counterparty.name if getattr(me, "counterparty", None) else "—"
    text = (
        f"📅 Ежемесячная трата\n\n"
        f"**{me.title}**\n"
        f"День месяца: {me.day_of_month}\n"
        f"Сумма: {me.amount} ₽\n"
        f"Категория: {cat_name}\n"
        f"Контрагент: {cp_name}\n"
        f"Комментарий: {me.comment or '—'}"
    )
    await callback.message.answer(text, parse_mode="Markdown", reply_markup=me_card_kb(me.id).as_markup())
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("me:hide:"))
async def me_hide(callback: CallbackQuery, session: AsyncSession, user: User | None):
    if not await require_owner_callback(callback, user, action="me_hide"):
        return
    me_id = int(callback.data.split(":")[-1])
    repo = Repo(session)
    ok, msg = await repo.deactivate_monthly_expense(me_id)
    await callback.message.answer(msg, reply_markup=me_menu_kb().as_markup())
    audit.info("me.hide | tg_id=%s | me_id=%s | ok=%s", callback.from_user.id, me_id, ok)
    await callback.answer()


# ---------- add flow ----------
@router.callback_query(lambda c: c.data == "me:add")
async def me_add_start(callback: CallbackQuery, state: FSMContext, user: User | None):
    if not await require_owner_callback(callback, user, action="me_add_start"):
        return
    await state.clear()
    await state.set_state(MonthlyExpenseFlow.add_title)
    await callback.message.answer("Название (например: Аренда, Интернет):", reply_markup=cancel_menu())
    await callback.answer()


@router.message(MonthlyExpenseFlow.add_title)
async def me_add_title(message: Message, state: FSMContext, user: User | None):
    if not await require_owner(message, user, action="me_add_title"):
        return
    title = " ".join((message.text or "").split())
    if len(title) < 2:
        await message.answer("Слишком коротко. Введите ещё раз.")
        return
    await state.update_data(title=title)
    await state.set_state(MonthlyExpenseFlow.add_day)
    await message.answer("День месяца (1..31):", reply_markup=cancel_menu())


@router.message(MonthlyExpenseFlow.add_day)
async def me_add_day(message: Message, state: FSMContext, user: User | None):
    if not await require_owner(message, user, action="me_add_day"):
        return
    try:
        day = int((message.text or "").strip())
    except Exception:
        day = 0
    if day < 1 or day > 31:
        await message.answer("Нужно число 1..31. Введите ещё раз.")
        return
    await state.update_data(day_of_month=day)
    await state.set_state(MonthlyExpenseFlow.add_amount)
    await message.answer("Сумма (₽, целое число):", reply_markup=cancel_menu())


@router.message(MonthlyExpenseFlow.add_amount)
async def me_add_amount(message: Message, session: AsyncSession, state: FSMContext, user: User | None):
    if not await require_owner(message, user, action="me_add_amount"):
        return
    amt = parse_amount(message.text)
    if not amt:
        await message.answer("Нужно целое положительное число. Например: 3500")
        return
    await state.update_data(amount=amt)

    repo = Repo(session)
    cats = await repo.list_categories(CategoryKind.expense)
    await state.set_state(MonthlyExpenseFlow.add_category)
    await message.answer("Категория расхода:", reply_markup=categories_kb([c.name for c in cats]))


@router.message(MonthlyExpenseFlow.add_category)
async def me_add_category(message: Message, session: AsyncSession, state: FSMContext, user: User | None):
    if not await require_owner(message, user, action="me_add_category"):
        return
    repo = Repo(session)
    text = (message.text or "").strip()

    if text in ("— Без категории", "-", "—"):
        await state.update_data(category_id=None, category_name="—")
    else:
        cat = await repo.get_category_by_name(CategoryKind.expense, text)
        if not cat:
            cats = await repo.list_categories(CategoryKind.expense)
            await message.answer("Выберите категорию кнопкой:", reply_markup=categories_kb([c.name for c in cats]))
            return
        await state.update_data(category_id=cat.id, category_name=cat.name)

    cps = await repo.list_counterparties(active_only=True)
    await state.set_state(MonthlyExpenseFlow.add_counterparty)
    if not cps:
        await state.update_data(counterparty_id=None, counterparty_name="—")
        await state.set_state(MonthlyExpenseFlow.add_comment)
        await message.answer("Комментарий (или /skip):", reply_markup=cancel_menu())
        return

    await message.answer("Контрагент:", reply_markup=counterparties_kb([c.name for c in cps]))


@router.message(MonthlyExpenseFlow.add_counterparty)
async def me_add_counterparty(message: Message, session: AsyncSession, state: FSMContext, user: User | None):
    if not await require_owner(message, user, action="me_add_counterparty"):
        return
    repo = Repo(session)
    text = (message.text or "").strip()

    if text in ("— Без контрагента", "-", "—"):
        await state.update_data(counterparty_id=None, counterparty_name="—")
    else:
        cps = await repo.list_counterparties(active_only=True)
        cp = next((c for c in cps if c.name == text), None)
        if not cp:
            await message.answer("Выберите контрагента кнопкой:", reply_markup=counterparties_kb([c.name for c in cps]))
            return
        await state.update_data(counterparty_id=cp.id, counterparty_name=cp.name)

    await state.set_state(MonthlyExpenseFlow.add_comment)
    await message.answer("Комментарий (необязательно). Чтобы пропустить — /skip", reply_markup=cancel_menu())


@router.message(MonthlyExpenseFlow.add_comment)
async def me_add_finish(message: Message, session: AsyncSession, state: FSMContext, user: User | None):
    if not await require_owner(message, user, action="me_add_finish"):
        return
    raw = (message.text or "").strip()
    comment = None if raw.lower() == "/skip" else (raw if raw else None)

    data = await state.get_data()
    repo = Repo(session)
    me = await repo.create_monthly_expense(
        title=data["title"],
        day_of_month=int(data["day_of_month"]),
        amount=int(data["amount"]),
        category_id=data.get("category_id"),
        counterparty_id=data.get("counterparty_id"),
        comment=comment,
    )
    await state.clear()

    cat_name = data.get("category_name") or "—"
    cp_name = data.get("counterparty_name") or "—"
    await message.answer(
        "✅ Добавлено.\n"
        f"{me.day_of_month:02d} — {me.title} — {me.amount} ₽\n"
        f"Категория: {cat_name}\n"
        f"Контрагент: {cp_name}\n"
        f"Комментарий: {me.comment or '—'}",
        reply_markup=me_menu_kb().as_markup(),
    )
    audit.info("me.create | tg_id=%s | me_id=%s | title=%s", message.from_user.id, me.id, me.title)


# ---------- apply current month ----------
@router.callback_query(lambda c: c.data == "me:apply")
async def me_apply(callback: CallbackQuery, session: AsyncSession, user: User | None):
    if not await require_owner_callback(callback, user, action="me_apply"):
        return

    repo = Repo(session)
    items = await repo.list_monthly_expenses(active_only=True)
    if not items:
        await callback.message.answer("Пока нет шаблонов.", reply_markup=me_menu_kb().as_markup())
        await callback.answer()
        return

    now = datetime.now(MSK)
    y, m = now.year, now.month
    created = 0
    skipped = 0

    for me in items:
        if await repo.monthly_expense_applied(me.id, y, m):
            skipped += 1
            continue

        marker = f"[ME:{me.id}:{y:04d}-{m:02d}]"
        base_comment = f"{marker} {me.title}"
        if me.comment:
            base_comment += f" | {me.comment}"

        await repo.add_operation(
            op_type=OperationType.expense,
            amount=me.amount,
            created_by_id=user.id,
            category_id=me.category_id,
            counterparty_id=me.counterparty_id,
            comment=base_comment,
        )
        created += 1

    await callback.message.answer(
        f"🧾 Готово за {y:04d}-{m:02d}\n"
        f"✅ Создано операций: {created}\n"
        f"⏭️ Уже было: {skipped}",
        reply_markup=me_menu_kb().as_markup(),
    )
    audit.info("me.apply | tg_id=%s | ym=%04d-%02d | created=%s | skipped=%s", callback.from_user.id, y, m, created, skipped)
    await callback.answer()
