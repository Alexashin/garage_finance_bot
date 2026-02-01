from __future__ import annotations

import logging

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import cancel_menu, confirm_menu, main_menu, reserve_menu
from app.models import Category, CategoryKind, OperationType, UserRole
from app.repository import Repo
from app.states import ExpenseFlow, IncomeFlow, ReserveFlow
from app.utils.money import parse_amount
from app.handlers.common import render_balance_message

logger = logging.getLogger(__name__)
router = Router()


def categories_kb(names: list[str]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=n)] for n in names]
    rows.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


@router.message(lambda m: m.text == "❌ Отмена")
async def cancel_any(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Ок, отменено.", reply_markup=main_menu())


# ---------- INCOME ----------
@router.message(lambda m: m.text == "🟢 Доход")
async def start_income(message: Message, session: AsyncSession, state: FSMContext):
    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer("⛔ Доступ запрещён.")
        return
    if user.role == UserRole.viewer:
        await message.answer("👁 Вы наблюдатель: добавлять операции нельзя.")
        return

    await state.set_state(IncomeFlow.amount)
    await state.update_data(kind="income")
    await message.answer(
        "Введите сумму дохода (целое число, ₽):", reply_markup=cancel_menu()
    )


@router.message(IncomeFlow.amount)
async def income_amount(message: Message, session: AsyncSession, state: FSMContext):
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
            reply_markup=main_menu(),
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
    cat = await repo.get_category_by_name(CategoryKind.income, message.text.strip())
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
        "Комментарий (опционально). Отправьте текст или '-' чтобы пропустить:",
        reply_markup=cancel_menu(),
    )


@router.message(IncomeFlow.comment)
async def income_comment(message: Message, session: AsyncSession, state: FSMContext):
    comment = message.text.strip()
    if comment == "-":
        comment = None

    data = await state.get_data()
    amt = int(data["amount"])

    # get category name for preview
    cat_obj = await session.get(Category, int(data["category_id"]))

    await state.update_data(comment=comment)
    await state.set_state(IncomeFlow.confirm)

    await message.answer(
        f"Подтвердите доход:\n\n💵 Сумма: {amt} ₽\n🏷 Категория: {cat_obj.name if cat_obj else ''}\n📝 Комментарий: {comment or '—'}",
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

    await state.clear()
    text = await render_balance_message(repo)
    await message.answer("✅ Доход записан.\n\n" + text, reply_markup=main_menu())


# ---------- EXPENSE ----------
@router.message(lambda m: m.text == "🔴 Расход")
async def start_expense(message: Message, session: AsyncSession, state: FSMContext):
    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer("⛔ Доступ запрещён.")
        return
    if user.role == UserRole.viewer:
        await message.answer("👁 Вы наблюдатель: добавлять операции нельзя.")
        return

    await state.set_state(ExpenseFlow.amount)
    await message.answer(
        "Введите сумму расхода (целое число, ₽):", reply_markup=cancel_menu()
    )


@router.message(ExpenseFlow.amount)
async def expense_amount(message: Message, session: AsyncSession, state: FSMContext):
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
            reply_markup=main_menu(),
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
    cat = await repo.get_category_by_name(CategoryKind.expense, message.text.strip())
    if not cat:
        cats = await repo.list_categories(CategoryKind.expense)
        await message.answer(
            "Выберите категорию кнопкой:",
            reply_markup=categories_kb([c.name for c in cats]),
        )
        return

    await state.update_data(category_id=cat.id)
    await state.set_state(ExpenseFlow.comment)
    await message.answer(
        "Комментарий (опционально). Отправьте текст или '-' чтобы пропустить:",
        reply_markup=cancel_menu(),
    )


@router.message(ExpenseFlow.comment)
async def expense_comment(message: Message, session: AsyncSession, state: FSMContext):
    comment = message.text.strip()
    if comment == "-":
        comment = None

    data = await state.get_data()
    amt = int(data["amount"])

    # get category name for preview
    cat_obj = await session.get(Category, int(data["category_id"]))

    await state.update_data(comment=comment)
    await state.set_state(ExpenseFlow.confirm)

    await message.answer(
        f"Подтвердите расход:\n\n💸 Сумма: {amt} ₽\n🏷 Категория: {cat_obj.name if cat_obj else ''}\n📝 Комментарий: {comment or '—'}",
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
    )

    await state.clear()
    text = await render_balance_message(repo)
    await message.answer("✅ Расход записан.\n\n" + text, reply_markup=main_menu())


# ---------- RESERVE ----------
@router.message(lambda m: m.text == "🛡 Резерв")
async def reserve_main(message: Message, session: AsyncSession):
    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer("⛔ Доступ запрещён.")
        return

    text = await render_balance_message(repo)
    await message.answer("🛡 Резерв\n\n" + text, reply_markup=reserve_menu())


@router.message(lambda m: m.text == "🟢 В резерв")
async def reserve_add_start(message: Message, session: AsyncSession, state: FSMContext):
    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer("⛔ Доступ запрещён.")
        return
    if user.role == UserRole.viewer:
        await message.answer("👁 Вы наблюдатель: операции запрещены.")
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
    await state.clear()
    text = await render_balance_message(repo)
    await message.answer("✅ Переведено в резерв.\n\n" + text, reply_markup=main_menu())


@router.message(lambda m: m.text == "🔴 Из резерва")
async def reserve_remove_start(
    message: Message, session: AsyncSession, state: FSMContext
):
    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer("⛔ Доступ запрещён.")
        return
    if user.role == UserRole.viewer:
        await message.answer("👁 Вы наблюдатель: операции запрещены.")
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
    await state.clear()
    text = await render_balance_message(repo)
    await message.answer("✅ Выведено из резерва.\n\n" + text, reply_markup=main_menu())


@router.message(lambda m: m.text == "🔙 Назад")
async def back_to_menu(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()
    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer("⛔ Доступ запрещён.")
        return
    text = await render_balance_message(repo)
    await message.answer(text, reply_markup=main_menu())
