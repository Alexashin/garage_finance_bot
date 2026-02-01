from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import main_menu
from app.models import OperationType, UserRole
from app.repository import Repo
from app.handlers.common import render_balance_message

logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")
router = Router()


def quick_report_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="10 операций"), KeyboardButton(text="20 операций")],
            [KeyboardButton(text="30 операций")],
            [KeyboardButton(text="Назад")],
        ],
        resize_keyboard=True,
    )


def report_kind_inline(prefix: str = "rk") -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="Всё", callback_data=f"{prefix}:all")
    kb.button(text="Доходы", callback_data=f"{prefix}:income")
    kb.button(text="Расходы", callback_data=f"{prefix}:expense")
    kb.adjust(1)
    return kb


def report_period_inline(prefix: str = "rp") -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="Последние 7 дней", callback_data=f"{prefix}:7")
    kb.button(text="Последние 30 дней", callback_data=f"{prefix}:30")
    kb.button(text="Последние 90 дней", callback_data=f"{prefix}:90")
    kb.button(
        text="Свой период", callback_data=f"{prefix}:custom"
    )  # пока не реализуем тут
    kb.adjust(1)
    return kb


def _op_types_from_kind(kind: str):
    if kind == "income":
        return [OperationType.income]
    if kind == "expense":
        return [OperationType.expense]
    return None  # all


def _period_from_days(days: int):
    end = datetime.now()
    start = end - timedelta(days=days)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start, end


def format_ops_lines(ops) -> str:
    # Ожидаем, что op имеет: created_at, op_type, amount, category?.name, comment
    lines = []
    for op in ops:
        dt = getattr(op, "created_at", None)
        dt_s = dt.strftime("%d.%m %H:%M") if dt else "—"
        t = getattr(op, "op_type", None)
        t_s = (
            "Доход"
            if t == OperationType.income
            else "Расход" if t == OperationType.expense else "Резерв"
        )
        amount = getattr(op, "amount", 0)
        cat = getattr(op, "category", None)
        cat_name = getattr(cat, "name", None) or "—"
        comment = getattr(op, "comment", None) or "—"
        lines.append(f"{dt_s} | {t_s} | {amount} ₽ | {cat_name} | {comment}")
    return "\n".join(lines) if lines else "Операций нет."


@router.message(lambda m: m.text == "📊 Отчёты")
async def reports_main(message: Message, session: AsyncSession, state: FSMContext):
    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user:
        audit.info("auth.denied | tg_id=%s | action=reports_main", message.from_user.id)
        await message.answer("⛔ Доступ запрещён.")
        return

    await state.clear()

    # Worker + Viewer: только быстрый отчёт
    if user.role in (UserRole.worker, UserRole.viewer):
        audit.info(
            "report.quick.open | tg_id=%s | user_id=%s | role=%s",
            message.from_user.id,
            user.id,
            user.role.value,
        )
        text = await render_balance_message(repo)
        await message.answer(
            "📊 Быстрый отчёт\n\n"
            + text
            + "\n\nВыберите количество последних операций:",
            reply_markup=quick_report_kb(),
        )
        return

    # Owner: сначала выбор типа данных, потом периода
    kb = report_kind_inline(prefix="rk").as_markup()
    await message.answer(
        "📊 Отчёты (для владельца)\n\nВыберите, что показать:",
        reply_markup=kb,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("rk:"))
async def report_owner_pick_kind(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
):
    repo = Repo(session)
    user = await repo.get_user_by_tg(callback.from_user.id)
    if not user or user.role != UserRole.owner:
        audit.info(
            "auth.denied | tg_id=%s | action=report_owner_pick_kind",
            callback.from_user.id,
        )
        await callback.answer("Нет прав", show_alert=True)
        return

    kind = callback.data.split(":", 1)[1]  # all/income/expense
    await state.update_data(report_kind=kind)

    kb = report_period_inline(prefix="rp").as_markup()
    await callback.message.answer("Выберите период:", reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("rp:"))
async def report_owner_pick_period(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
):
    repo = Repo(session)
    user = await repo.get_user_by_tg(callback.from_user.id)
    if not user or user.role != UserRole.owner:
        audit.info(
            "auth.denied | tg_id=%s | action=report_owner_pick_period",
            callback.from_user.id,
        )
        await callback.answer("Нет прав", show_alert=True)
        return

    period = callback.data.split(":", 1)[1]  # 7/30/90/custom
    if period == "custom":
        await callback.answer(
            "Кастомный период добавим следующим шагом.", show_alert=True
        )
        return

    days = int(period)
    start, end = _period_from_days(days)

    data = await state.get_data()
    kind = data.get("report_kind", "all")
    op_types = _op_types_from_kind(kind)

    ops = await repo.list_operations_filtered(op_types=op_types, start=start, end=end)

    # Итоги
    income_sum = sum(o.amount for o in ops if o.op_type == OperationType.income)
    expense_sum = sum(o.amount for o in ops if o.op_type == OperationType.expense)

    bal_text = await render_balance_message(repo)
    text = (
        f"📊 Отчёт за последние {days} дней\n"
        f"Показано: {'Всё' if kind=='all' else 'Доходы' if kind=='income' else 'Расходы'}\n\n"
        f"{bal_text}\n\n"
        f"🟢 Доходы: {income_sum} ₽\n"
        f"🔴 Расходы: {expense_sum} ₽\n\n"
        f"Последние 20 операций за период:\n"
    )

    # последние 20 (предполагаем, что repo отдаёт по времени)
    tail = ops[:20]
    text += format_ops_lines(tail)

    audit.info(
        "report.generated | owner_tg=%s | days=%s | kind=%s | ops=%s",
        callback.from_user.id,
        days,
        kind,
        len(ops),
    )

    await state.clear()
    await callback.message.answer(text, reply_markup=main_menu(user.role))
    await callback.answer()


@router.message(lambda m: m.text in {"10 операций", "20 операций", "30 операций"})
async def quick_report_last_ops(
    message: Message, session: AsyncSession, state: FSMContext
):
    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user:
        audit.info(
            "auth.denied | tg_id=%s | action=quick_report_last_ops",
            message.from_user.id,
        )
        await message.answer("⛔ Доступ запрещён.")
        return

    # viewer/worker/owner — всем можно быстрый
    n = int((message.text or "10").split()[0])

    # Берём “все операции” и режем последние N.
    # Лучше потом добавить Repo.list_last_operations(limit=n).
    ops = await repo.list_operations_filtered(op_types=None, start=None, end=None)
    tail = ops[:n]

    bal_text = await render_balance_message(repo)
    text = (
        "📊 Быстрый отчёт\n\n"
        + bal_text
        + f"\n\nПоследние {n} операций:\n"
        + format_ops_lines(tail)
    )

    audit.info(
        "report.quick | tg_id=%s | user_id=%s | n=%s", message.from_user.id, user.id, n
    )
    await message.answer(text, reply_markup=quick_report_kb())


@router.message(lambda m: m.text == "Назад")
async def reports_back(message: Message, session: AsyncSession, state: FSMContext):
    await state.clear()
    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer("⛔ Доступ запрещён.")
        return
    text = await render_balance_message(repo)
    await message.answer(text, reply_markup=main_menu(user.role))
