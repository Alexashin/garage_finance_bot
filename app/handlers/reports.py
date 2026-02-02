from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import FSInputFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.handlers.common import render_balance_message
from app.keyboards import main_menu
from app.models import OperationType, UserRole, User
from app.repository import Repo
from app.utils.csv_export import export_operations_csv
from app.utils.guards import require_owner_callback, require_user

logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")
router = Router()

MSK = ZoneInfo("Europe/Moscow")


class ReportCustomPeriod(StatesGroup):
    start_date = State()  # DD.MM.YYYY
    end_date = State()  # DD.MM.YYYY


# ---------- UI builders ----------
def report_kind_inline(prefix: str = "rk") -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="Всё", callback_data=f"{prefix}:all")
    kb.button(text="Доходы", callback_data=f"{prefix}:income")
    kb.button(text="Расходы", callback_data=f"{prefix}:expense")
    kb.adjust(1)
    return kb


def report_period_inline(prefix: str = "rp") -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="7 дней", callback_data=f"{prefix}:7")
    kb.button(text="14 дней", callback_data=f"{prefix}:14")
    kb.button(text="30 дней", callback_data=f"{prefix}:30")
    kb.button(text="Свой период", callback_data=f"{prefix}:custom")
    kb.adjust(1)
    return kb


def owner_export_inline(prefix: str = "re") -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="📄 Выгрузить CSV", callback_data=f"{prefix}:csv")
    kb.adjust(1)
    return kb


# ---------- helpers ----------
def _op_types_from_kind(kind: str):
    if kind == "income":
        return [OperationType.income]
    if kind == "expense":
        return [OperationType.expense]
    return None  # all


def _msk_day_bounds(dt_msk: datetime) -> tuple[datetime, datetime]:
    start = dt_msk.replace(hour=0, minute=0, second=0, microsecond=0)
    end = dt_msk.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start, end


def _period_from_days_msk(days: int) -> tuple[datetime, datetime]:
    now = datetime.now(MSK)
    start_day, _ = _msk_day_bounds(now - timedelta(days=days - 1))
    _, end_day = _msk_day_bounds(now)
    return start_day, end_day


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.astimezone(timezone.utc)


def _fmt_dt_msk(dt: datetime | None) -> str:
    if not dt:
        return "—"
    try:
        return dt.astimezone(MSK).strftime("%d.%m %H:%M")
    except Exception:
        return dt.strftime("%d.%m %H:%M")


def _type_ru(t: OperationType | None) -> str:
    if t == OperationType.income:
        return "Доход"
    if t == OperationType.expense:
        return "Расход"
    if t in (OperationType.reserve_in, OperationType.reserve_out):
        return "Резерв"
    return "—"


def format_ops_lines(ops) -> str:
    lines = []
    for op in ops:
        dt_s = _fmt_dt_msk(getattr(op, "created_at", None))
        t_s = _type_ru(getattr(op, "op_type", None))
        amount = getattr(op, "amount", 0)

        cat = getattr(op, "category", None)
        cat_name = getattr(cat, "name", None) or "—"

        created_by = getattr(op, "created_by", None)
        created_by_name = (
            getattr(created_by, "name", None) or f"#{getattr(op, 'created_by_id', '—')}"
        )

        comment = getattr(op, "comment", None) or "—"
        lines.append(
            f"{dt_s} | {t_s} | {amount} ₽ | {cat_name} | {created_by_name} | {comment}"
        )

    return "\n".join(lines) if lines else "Операций нет."


# async def _require_user(repo: Repo, tg_id: int):
#     user = await repo.get_user_by_tg(tg_id)
#     return user


def _scope_created_by_id(user) -> int | None:
    # worker/viewer видят только свои операции
    if user and user.role in (UserRole.worker, UserRole.viewer):
        return user.id
    return None


async def _generate_report_text(
    repo: Repo, user, kind: str, start_msk: datetime, end_msk: datetime
) -> tuple[str, list]:
    op_types = _op_types_from_kind(kind)
    created_by_id = _scope_created_by_id(user)

    # В БД сравниваем в UTC (created_at = timestamptz)
    start = _to_utc(start_msk)
    end = _to_utc(end_msk)

    ops = await repo.list_operations_filtered(
        op_types=op_types,
        start=start,
        end=end,
        created_by_id=created_by_id,
    )

    income_sum = sum(o.amount for o in ops if o.op_type == OperationType.income)
    expense_sum = sum(o.amount for o in ops if o.op_type == OperationType.expense)

    bal_text = await render_balance_message(repo)

    kind_ru = "Всё" if kind == "all" else ("Доходы" if kind == "income" else "Расходы")
    period_ru = f"{start_msk.strftime('%d.%m.%Y')} — {end_msk.strftime('%d.%m.%Y')}"

    header = f"📊 Отчёт\nПоказано: {kind_ru}\nПериод: {period_ru}\n\n{bal_text}\n\n🟢 Доходы: {income_sum} ₽\n🔴 Расходы: {expense_sum} ₽\n\n"
    tail = ops[:20]
    body = "Последние 20 операций за период:\n" + format_ops_lines(tail)

    if user and user.role == UserRole.owner:
        body += "\n\n(В строках указано, кто внёс операцию.)"
    else:
        body += "\n\n(Показаны только ваши операции.)"

    return header + body, ops


# ---------- Handlers ----------
@router.message(lambda m: m.text == "📊 Отчёты")
async def reports_main(message: Message, state: FSMContext, user: User | None):
    if not await require_user(message, user):
        return

    await state.clear()
    await state.update_data(report_scope_owner=(user.role == UserRole.owner))

    kb = report_kind_inline(prefix="rk").as_markup()
    await message.answer("📊 Отчёты\n\nВыберите тип данных:", reply_markup=kb)


@router.callback_query(lambda c: c.data and c.data.startswith("rk:"))
async def report_pick_kind(
    callback: CallbackQuery, state: FSMContext, user: User | None
):
    if not await require_owner_callback(callback, user, action="report_pick_kind"):
        return

    kind = callback.data.split(":", 1)[1]  # all/income/expense
    await state.update_data(report_kind=kind)

    kb = report_period_inline(prefix="rp").as_markup()
    await callback.message.answer("Выберите период:", reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("rp:"))
async def report_pick_period(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, user: User | None
):
    repo = Repo(session)
    if not await require_owner_callback(callback, user, action="report_pick_period"):
        return
    period = callback.data.split(":", 1)[1]  # 7/14/30/custom
    data = await state.get_data()
    kind = data.get("report_kind", "all")

    if period == "custom":
        await state.set_state(ReportCustomPeriod.start_date)
        await callback.message.answer("Введите дату начала (ДД.ММ.ГГГГ):")
        await callback.answer()
        return

    days = int(period)
    start_msk, end_msk = _period_from_days_msk(days)

    text, ops = await _generate_report_text(repo, user, kind, start_msk, end_msk)

    # Для owner сохраняем параметры отчёта, чтобы можно было выгрузить CSV
    if user.role == UserRole.owner:
        await state.update_data(
            last_report=dict(
                kind=kind,
                start_utc=_to_utc(start_msk).isoformat(),
                end_utc=_to_utc(end_msk).isoformat(),
            )
        )
        kb = owner_export_inline(prefix="re").as_markup()
        await callback.message.answer(text, reply_markup=kb)
    else:
        await callback.message.answer(text, reply_markup=main_menu(user.role))

    audit.info(
        "report.generated | tg_id=%s | role=%s | kind=%s | period=%s | ops=%s",
        callback.from_user.id,
        user.role.value,
        kind,
        period,
        len(ops),
    )
    await callback.answer()


@router.message(ReportCustomPeriod.start_date)
async def report_custom_start(message: Message, state: FSMContext, user: User | None):
    if not await require_user(message, user):
        return

    raw = (message.text or "").strip()
    try:
        start_date = datetime.strptime(raw, "%d.%m.%Y").replace(tzinfo=MSK)
    except ValueError:
        await message.answer("Не понял дату. Формат: ДД.ММ.ГГГГ (например 05.02.2026)")
        return

    await state.update_data(custom_start=raw)
    await state.set_state(ReportCustomPeriod.end_date)
    await message.answer("Введите дату окончания (ДД.ММ.ГГГГ):")


@router.message(ReportCustomPeriod.end_date)
async def report_custom_end(
    message: Message, session: AsyncSession, state: FSMContext, user: User | None
):

    if not await require_user(message, user):
        return

    repo = Repo(session)
    data = await state.get_data()
    kind = data.get("report_kind", "all")
    start_raw = data.get("custom_start")

    raw = (message.text or "").strip()
    try:
        start_date = datetime.strptime(start_raw, "%d.%m.%Y").replace(tzinfo=MSK)
    except Exception:
        await state.clear()
        await message.answer("Сбилось состояние. Попробуйте снова: 📊 Отчёты")
        return

    try:
        end_date = datetime.strptime(raw, "%d.%m.%Y").replace(tzinfo=MSK)
    except ValueError:
        await message.answer("Не понял дату. Формат: ДД.ММ.ГГГГ (например 12.02.2026)")
        return

    if end_date < start_date:
        await message.answer(
            "Дата окончания меньше даты начала. Введите дату окончания ещё раз."
        )
        return

    start_msk, _ = _msk_day_bounds(start_date)
    _, end_msk = _msk_day_bounds(end_date)

    text, ops = await _generate_report_text(repo, user, kind, start_msk, end_msk)

    if user.role == UserRole.owner:
        await state.update_data(
            last_report=dict(
                kind=kind,
                start_utc=_to_utc(start_msk).isoformat(),
                end_utc=_to_utc(end_msk).isoformat(),
            )
        )
        kb = owner_export_inline(prefix="re").as_markup()
        await message.answer(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=main_menu(user.role))

    audit.info(
        "report.generated | tg_id=%s | role=%s | kind=%s | period=custom | ops=%s",
        message.from_user.id,
        user.role.value,
        kind,
        len(ops),
    )
    # Очищаем только state-машину, но для владельца оставляем last_report для экспорта
    if user.role == UserRole.owner:
        await state.set_state(None)
    else:
        await state.clear()


@router.callback_query(lambda c: c.data == "re:csv")
async def report_export_csv(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, user: User | None
):
    repo = Repo(session)
    if not await require_owner_callback(callback, user, action="report_export_csv"):
        return

    data = await state.get_data()
    last = data.get("last_report")
    if not last:
        await callback.answer("Сначала сформируйте отчёт.", show_alert=True)
        return

    try:
        kind = last["kind"]
        start = datetime.fromisoformat(last["start_utc"])
        end = datetime.fromisoformat(last["end_utc"])
    except Exception:
        await callback.answer("Не смог прочитать параметры отчёта.", show_alert=True)
        return

    op_types = _op_types_from_kind(kind)
    ops = await repo.list_operations_filtered(op_types=op_types, start=start, end=end)

    path = export_operations_csv(ops)
    await callback.message.answer_document(
        FSInputFile(path, filename="report.csv"),
        caption="📄 CSV-отчёт (открывается в Excel).",
    )

    audit.info(
        "report.export.csv | owner_tg=%s | kind=%s | ops=%s",
        callback.from_user.id,
        kind,
        len(ops),
    )
    await callback.answer("Готово")
