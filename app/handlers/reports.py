from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.keyboards import cancel_menu, main_menu, reports_menu
from app.models import OperationType, UserRole
from app.repository import Repo
from app.states import ReportFlow
from app.utils.csv_export import export_operations_csv
from app.handlers.common import render_balance_message

logger = logging.getLogger(__name__)
router = Router()


def _parse_period_text(text: str) -> tuple[datetime | None, datetime | None] | None:
    """Supported: '7', '30', 'all', or 'YYYY-MM-DD YYYY-MM-DD'."""
    t = (text or "").strip()
    if not t:
        return None
    if t.lower() in {"all", "всё", "все", "за всё время"}:
        return None, None
    if t in {"7", "7д", "7дней"}:
        end = datetime.now()
        return end - timedelta(days=7), end
    if t in {"30", "30д", "30дней"}:
        end = datetime.now()
        return end - timedelta(days=30), end

    parts = t.replace(",", " ").split()
    if len(parts) != 2:
        return None
    try:
        start = datetime.fromisoformat(parts[0])
        end = datetime.fromisoformat(parts[1])
    except ValueError:
        return None
    if start > end:
        return None
    # normalize
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start, end


@router.message(lambda m: m.text == "📊 Отчёты")
async def reports_main(message: Message, session: AsyncSession, state: FSMContext):
    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer("⛔ Доступ запрещён.")
        return

    await state.clear()
    await state.set_state(ReportFlow.kind)
    await message.answer(
        "📊 Отчёт (CSV)\n\n"
        "1) Напишите тип: all / income / expense\n"
        "2) Потом период: all, 7, 30 или две даты YYYY-MM-DD YYYY-MM-DD\n\n"
        "Можно отменить кнопкой.",
        reply_markup=reports_menu(),
    )


@router.message(lambda m: m.text == "📁 Скачать CSV")
async def reports_download_button(message: Message, session: AsyncSession, state: FSMContext):
    await reports_main(message, session, state)


@router.message(ReportFlow.kind)
async def report_kind(message: Message, session: AsyncSession, state: FSMContext):
    t = (message.text or "").strip().lower()
    mapping = {
        "all": None,
        "income": [OperationType.income],
        "expense": [OperationType.expense],
        "доход": [OperationType.income],
        "расход": [OperationType.expense],
        "все": None,
    }
    if t not in mapping:
        await message.answer("Введите: all / income / expense", reply_markup=cancel_menu())
        return

    await state.update_data(op_types=mapping[t])
    await state.set_state(ReportFlow.period)
    await message.answer(
        "Период?\n\n"
        "• all — за всё время\n"
        "• 7 — последние 7 дней\n"
        "• 30 — последние 30 дней\n"
        "• две даты: YYYY-MM-DD YYYY-MM-DD",
        reply_markup=cancel_menu(),
    )


@router.message(ReportFlow.period)
async def report_period(message: Message, session: AsyncSession, state: FSMContext):
    parsed = _parse_period_text(message.text)
    if parsed is None:
        await message.answer("Не понял период. Пример: 2026-01-01 2026-01-31", reply_markup=cancel_menu())
        return

    start, end = parsed
    data = await state.get_data()
    op_types = data.get("op_types")

    repo = Repo(session)
    user = await repo.get_user_by_tg(message.from_user.id)
    if not user:
        await state.clear()
        await message.answer("⛔ Доступ запрещён.")
        return

    # viewers allowed, workers allowed too (they can export)
    ops = await repo.list_operations_filtered(op_types=op_types, start=start, end=end)
    # preload category relation (simple lazy load is fine for CSV size here)

    path = export_operations_csv(ops)
    try:
        await message.answer_document(FSInputFile(path, filename="report.csv"))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    await state.clear()
    text = await render_balance_message(repo)
    await message.answer(text, reply_markup=main_menu())
