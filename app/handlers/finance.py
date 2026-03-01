from __future__ import annotations

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import cancel_menu, confirm_menu, main_menu, reserve_menu
from app.models import (
    Category,
    CategoryKind,
    OperationType,
    User,
    UserRole,
    Counterparty,
)
from app.repository import Repo
from app.states import ExpenseFlow, IncomeFlow, ReserveFlow
from app.utils.guards import require_user
from app.utils.money import parse_amount
from app.handlers.common import render_balance_message

logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")
router = Router()


async def get_current_user(session, tg_id: int) -> User | None:
    return await Repo(session).get_user_by_tg(tg_id)


def categories_kb(names: list[str]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=n)] for n in names]
    rows.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def counterparties_kb(names: list[str]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="— Без контрагента")]]
    rows += [[KeyboardButton(text=n)] for n in names]
    rows.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


@router.message(lambda m: m.text == "❌ Отмена")
async def cancel_any(message: Message, state: FSMContext, user: User | None):
    await state.clear()
    await message.answer("Ок, отменено.", reply_markup=main_menu(user.role))


# ---------- INCOME ----------
@router.message(lambda m: m.text == "🟢 Доход")
async def start_income(message: Message, state: FSMContext, user: User | None):
    if not await require_user(message, user):
        return

    if user.role == UserRole.viewer:
        audit.info(
            "auth.denied | tg_id=%s | user_id=%s | role=viewer | action=add_income",
            message.from_user.id,
            user.id,
        )
        await message.answer("👁 Наблюдатель: добавлять операции нельзя.")
        return

    await state.set_state(IncomeFlow.amount)
    await state.update_data(kind="income")
    await message.answer(
        "Введите сумму дохода (целое число, ₽):", reply_markup=cancel_menu()
    )


@router.message(IncomeFlow.amount)
async def income_amount(
    message: Message, session: AsyncSession, state: FSMContext, user
):
    amt = parse_amount(message.text)
    if not amt:
        await message.answer(
            "Нужно целое положительное число. Например: 3500",
            reply_markup=cancel_menu(),
        )
        return
    await state.update_data(amount=amt)

    repo = Repo(session)
    cats = await repo.list_categories(CategoryKind.income)
    if not cats:
        await message.answer(
            "Нет категорий доходов в БД. Обратитесь к владельцу.",
            reply_markup=main_menu(user.role),
        )
        await state.clear()
        return

    await state.set_state(IncomeFlow.category)
    await message.answer(
        "Выберите категорию дохода:", reply_markup=categories_kb([c.name for c in cats])
    )


@router.message(IncomeFlow.category)
async def income_category(message: Message, session: AsyncSession, state: FSMContext):
    repo = Repo(session)
    text = (message.text or "").strip()
    cat = await repo.get_category_by_name(CategoryKind.income, text)
    if not cat:
        cats = await repo.list_categories(CategoryKind.income)
        await message.answer(
            "Выберите категорию кнопкой:",
            reply_markup=categories_kb([c.name for c in cats]),
        )
        return

    await state.update_data(category_id=cat.id)
    await state.set_state(IncomeFlow.comment)
    await message.answer(
        "Комментарий (необязательно). Чтобы пропустить — отправь /skip",
        reply_markup=cancel_menu(),
    )


@router.message(IncomeFlow.comment)
async def income_comment(message: Message, session: AsyncSession, state: FSMContext):
    raw = (message.text or "").strip()
    comment = None if raw.lower() == "/skip" else (raw if raw else None)

    data = await state.get_data()
    amt = int(data["amount"])
    cat_obj = await session.get(Category, int(data["category_id"]))

    await state.update_data(comment=comment)
    await state.set_state(IncomeFlow.confirm)

    await message.answer(
        "Подтвердите доход:\n\n"
        f"💵 Сумма: {amt} ₽\n"
        f"🏷 Категория: {cat_obj.name if cat_obj else ''}\n"
        f"📝 Комментарий: {comment or '—'}",
        reply_markup=confirm_menu(),
    )


@router.message(IncomeFlow.confirm)
async def income_confirm(message: Message, session: AsyncSession, state: FSMContext):
    if message.text != "✅ Подтвердить":
        await message.answer(
            "Нажмите ✅ Подтвердить или ❌ Отмена", reply_markup=confirm_menu()
        )
        return

    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user or user.role == UserRole.viewer:
        audit.info(
            "auth.denied | tg_id=%s | action=income_confirm", message.from_user.id
        )
        await message.answer("⛔ Нет прав.")
        await state.clear()
        return

    data = await state.get_data()
    await repo.add_operation(
        op_type=OperationType.income,
        amount=int(data["amount"]),
        category_id=int(data["category_id"]),
        comment=data.get("comment"),
        created_by_id=user.id,
    )

    audit.info(
        "op.added | user_id=%s | tg_id=%s | type=income | amount=%s | category_id=%s",
        user.id,
        user.telegram_id,
        data["amount"],
        data["category_id"],
    )

    await state.clear()
    text = await render_balance_message(repo)
    await message.answer(
        "✅ Доход записан.\n\n" + text, reply_markup=main_menu(user.role)
    )


# ---------- EXPENSE ----------
@router.message(lambda m: m.text == "🔴 Расход")
async def start_expense(message: Message, state: FSMContext, user: User | None):
    if not await require_user(message, user):
        return
    if user.role == UserRole.viewer:
        audit.info(
            "auth.denied | tg_id=%s | user_id=%s | role=viewer | action=add_expense",
            message.from_user.id,
            user.id,
        )
        await message.answer("👁 Наблюдатель: добавлять операции нельзя.")
        return

    await state.set_state(ExpenseFlow.amount)
    await message.answer(
        "Введите сумму расхода (целое число, ₽):", reply_markup=cancel_menu()
    )


@router.message(ExpenseFlow.amount)
async def expense_amount(
    message: Message, session: AsyncSession, state: FSMContext, user
):
    amt = parse_amount(message.text)
    if not amt:
        await message.answer(
            "Нужно целое положительное число. Например: 1200",
            reply_markup=cancel_menu(),
        )
        return

    repo = Repo(session)
    _, _, available = await repo.balance()
    if amt > available:
        await message.answer(
            f"Недостаточно средств. Доступно: {available} ₽", reply_markup=cancel_menu()
        )
        return

    await state.update_data(amount=amt)
    cats = await repo.list_categories(CategoryKind.expense)
    if not cats:
        await message.answer(
            "Нет категорий расходов в БД. Обратитесь к владельцу.",
            reply_markup=main_menu(user.role),
        )
        await state.clear()
        return

    await state.set_state(ExpenseFlow.category)
    await message.answer(
        "Выберите категорию расхода:",
        reply_markup=categories_kb([c.name for c in cats]),
    )


@router.message(ExpenseFlow.category)
async def expense_category(message: Message, session: AsyncSession, state: FSMContext):
    repo = Repo(session)
    text = (message.text or "").strip()
    cat = await repo.get_category_by_name(CategoryKind.expense, text)
    if not cat:
        cats = await repo.list_categories(CategoryKind.expense)
        await message.answer(
            "Выберите категорию кнопкой:",
            reply_markup=categories_kb([c.name for c in cats]),
        )
        return

    await state.update_data(category_id=cat.id)
    cps = await repo.list_counterparties(active_only=True)
    if not cps:
        # если контрагентов нет — пропускаем шаг
        await state.update_data(counterparty_id=None)
        await state.set_state(ExpenseFlow.comment)
        await message.answer(
            "Комментарий (необязательно). Чтобы пропустить — отправь /skip",
            reply_markup=cancel_menu(),
        )
        return

    await state.set_state(ExpenseFlow.counterparty)
    await message.answer(
        "Выберите контрагента (или '— Без контрагента'):",
        reply_markup=counterparties_kb([c.name for c in cps]),
    )


@router.message(ExpenseFlow.counterparty)
async def expense_counterparty(
    message: Message, session: AsyncSession, state: FSMContext
):
    repo = Repo(session)
    text = (message.text or "").strip()

    if text in ("— Без контрагента", "-", "—"):
        await state.update_data(counterparty_id=None, counterparty_name="—")
        await state.set_state(ExpenseFlow.comment)
        await message.answer(
            "Комментарий (необязательно). Чтобы пропустить — отправь /skip",
            reply_markup=cancel_menu(),
        )
        return

    # ищем контрагента по имени из кнопки
    cps = await repo.list_counterparties(active_only=True)
    cp = next((c for c in cps if c.name == text), None)
    if not cp:
        await message.answer(
            "Выберите контрагента кнопкой:",
            reply_markup=counterparties_kb([c.name for c in cps]),
        )
        return

    await state.update_data(counterparty_id=cp.id, counterparty_name=cp.name)
    await state.set_state(ExpenseFlow.comment)
    await message.answer(
        "Комментарий (необязательно). Чтобы пропустить — отправь /skip",
        reply_markup=cancel_menu(),
    )


@router.message(ExpenseFlow.comment)
async def expense_comment(message: Message, session: AsyncSession, state: FSMContext):
    raw = (message.text or "").strip()
    comment = None if raw.lower() == "/skip" else (raw if raw else None)

    data = await state.get_data()
    amt = int(data["amount"])
    cat_obj = await session.get(Category, int(data["category_id"]))

    await state.update_data(comment=comment)
    await state.set_state(ExpenseFlow.confirm)

    cp_name = data.get("counterparty_name") or "—"

    await message.answer(
        "Подтвердите расход:\n\n"
        f"💸 Сумма: {amt} ₽\n"
        f"🏷 Категория: {cat_obj.name if cat_obj else ''}\n"
        f"🏢 Контрагент: {cp_name}\n"
        f"📝 Комментарий: {comment or '—'}",
        reply_markup=confirm_menu(),
    )


@router.message(ExpenseFlow.confirm)
async def expense_confirm(message: Message, session: AsyncSession, state: FSMContext):
    if message.text != "✅ Подтвердить":
        await message.answer(
            "Нажмите ✅ Подтвердить или ❌ Отмена", reply_markup=confirm_menu()
        )
        return

    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user or user.role == UserRole.viewer:
        audit.info(
            "auth.denied | tg_id=%s | action=expense_confirm", message.from_user.id
        )
        await message.answer("⛔ Нет прав.")
        await state.clear()
        return

    data = await state.get_data()
    await repo.add_operation(
        op_type=OperationType.expense,
        amount=int(data["amount"]),
        category_id=int(data["category_id"]),
        comment=data.get("comment"),
        created_by_id=user.id,
        counterparty_id=data.get("counterparty_id"),
    )

    audit.info(
        "op.added | user_id=%s | tg_id=%s | type=expense | amount=%s | category_id=%s | counterparty_id=%s",
        user.id,
        user.telegram_id,
        data["amount"],
        data["category_id"],
        data.get("counterparty_id"),
    )

    await state.clear()
    text = await render_balance_message(repo)
    await message.answer(
        "✅ Расход записан.\n\n" + text, reply_markup=main_menu(user.role)
    )


# ---------- RESERVE ----------
@router.message(lambda m: m.text == "🛡 Резерв")
async def reserve_main(message: Message, session: AsyncSession, user: User | None):

    if not await require_user(message, user):
        return
    repo = Repo(session)
    text = await render_balance_message(repo)
    await message.answer("🛡 Резерв\n\n" + text, reply_markup=reserve_menu())


@router.message(lambda m: m.text == "🟢 В резерв")
async def reserve_add_start(
    message: Message, session: AsyncSession, state: FSMContext, user: User | None
):
    if not await require_user(message, user):
        return
    if user.role == UserRole.viewer:
        audit.info(
            "auth.denied | tg_id=%s | user_id=%s | role=viewer | action=reserve_in",
            message.from_user.id,
            user.id,
        )
        await message.answer("👁 Наблюдатель: операции запрещены.")
        return

    await state.set_state(ReserveFlow.add_amount)
    await message.answer(
        "Введите сумму для перевода в резерв:", reply_markup=cancel_menu()
    )


@router.message(ReserveFlow.add_amount)
async def reserve_add_amount(
    message: Message, session: AsyncSession, state: FSMContext
):
    amt = parse_amount(message.text)
    if not amt:
        await message.answer(
            "Нужно целое положительное число.", reply_markup=cancel_menu()
        )
        return

    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user or user.role == UserRole.viewer:
        audit.info(
            "auth.denied | tg_id=%s | action=reserve_in_confirm", message.from_user.id
        )
        await message.answer("⛔ Нет прав.")
        await state.clear()
        return

    _, _, available = await repo.balance()
    if amt > available:
        await message.answer(
            f"Недостаточно средств. Доступно: {available} ₽", reply_markup=cancel_menu()
        )
        return

    await repo.add_operation(
        OperationType.reserve_in, amt, user.id, category_id=None, comment="reserve"
    )

    audit.info(
        "reserve.in | user_id=%s | tg_id=%s | amount=%s", user.id, user.telegram_id, amt
    )

    await state.clear()
    text = await render_balance_message(repo)
    await message.answer(
        "✅ Переведено в резерв.\n\n" + text, reply_markup=main_menu(user.role)
    )


@router.message(lambda m: m.text == "🔴 Из резерва")
async def reserve_remove_start(
    message: Message, session: AsyncSession, state: FSMContext, user: User | None
):
    if not await require_user(message, user):
        return
    if user.role == UserRole.viewer:
        audit.info(
            "auth.denied | tg_id=%s | user_id=%s | role=viewer | action=reserve_out",
            message.from_user.id,
            user.id,
        )
        await message.answer("👁 Наблюдатель: операции запрещены.")
        return

    await state.set_state(ReserveFlow.remove_amount)
    await message.answer(
        "Введите сумму для вывода из резерва:", reply_markup=cancel_menu()
    )


@router.message(ReserveFlow.remove_amount)
async def reserve_remove_amount(
    message: Message, session: AsyncSession, state: FSMContext
):
    amt = parse_amount(message.text)
    if not amt:
        await message.answer(
            "Нужно целое положительное число.", reply_markup=cancel_menu()
        )
        return

    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user or user.role == UserRole.viewer:
        audit.info(
            "auth.denied | tg_id=%s | action=reserve_out_confirm", message.from_user.id
        )
        await message.answer("⛔ Нет прав.")
        await state.clear()
        return

    _, reserve, _ = await repo.balance()
    if amt > reserve:
        await message.answer(
            f"В резерве недостаточно. Сейчас: {reserve} ₽", reply_markup=cancel_menu()
        )
        return

    await repo.add_operation(
        OperationType.reserve_out, amt, user.id, category_id=None, comment="reserve"
    )

    audit.info(
        "reserve.out | user_id=%s | tg_id=%s | amount=%s",
        user.id,
        user.telegram_id,
        amt,
    )

    await state.clear()
    text = await render_balance_message(repo)
    await message.answer(
        "✅ Выведено из резерва.\n\n" + text, reply_markup=main_menu(user.role)
    )


@router.message(lambda m: m.text == "Назад")
async def back_to_menu(
    message: Message, state: FSMContext, session: AsyncSession, user: User | None
):
    await state.clear()
    if not await require_user(message, user):
        return
    repo = Repo(session)
    text = await render_balance_message(repo)
    await message.answer(text, reply_markup=main_menu(user.role))
