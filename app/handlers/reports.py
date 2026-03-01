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
from app.models import Operation, OperationType, UserRole, User
from app.repository import Repo
from app.utils.csv_export import export_operations_csv
from app.utils.guards import require_user, require_user_callback

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
    kb.button(text="1 день", callback_data=f"{prefix}:1")
    kb.button(text="3 дня", callback_data=f"{prefix}:3")
    kb.button(text="7 дней", callback_data=f"{prefix}:7")
    kb.button(text="Свой период (CSV)", callback_data=f"{prefix}:custom")
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


def format_ops_lines(ops: list[Operation]) -> str:
    lines = []
    for op in ops:
        dt_s = _fmt_dt_msk(getattr(op, "created_at", None))
        t_s = _type_ru(getattr(op, "op_type", None))
        amount = getattr(op, "amount", 0)

        cat = getattr(op, "category", None)
        cat_name = getattr(cat, "name", None) or "—"

        cp = getattr(op, "counterparty", None)
        cp_name = getattr(cp, "name", None) or "—"

        created_by = getattr(op, "created_by", None)
        created_by_name = (
            getattr(created_by, "name", None) or f"#{getattr(op, 'created_by_id', '—')}"
        )

        comment = getattr(op, "comment", None) or "—"
        lines.append(
            f"{dt_s} | {t_s} | {amount} ₽ | {cat_name} | {cp_name} | {created_by_name} | {comment}"
        )

    return "\n".join(lines) if lines else "Операций нет."


def _day_title(d, today):
    if d == today:
        return "Сегодня"
    if d == (today - timedelta(days=1)):
        return "Вчера"
    return d.strftime("%d.%m.%Y")


def format_ops_compact_by_day(ops: list, *, is_owner: bool) -> str:
    """
    Компактный вывод по дням:
    Сегодня:
    🟢Андрей 5000 Продажа "комм"
    ...
    """
    if not ops:
        return "Операций за период нет."

    # Группируем по дате в MSK
    by_day = {}
    for o in ops:
        dt_msk = o.created_at.astimezone(MSK)
        d = dt_msk.date()
        by_day.setdefault(d, []).append((dt_msk, o))

    today = datetime.now(MSK).date()
    days_sorted = sorted(by_day.keys(), reverse=True)

    lines: list[str] = []
    for d in days_sorted:
        lines.append(f"{_day_title(d, today)}:")
        items = sorted(by_day[d], key=lambda x: x[0], reverse=True)
        for _, o in items:
            icon = (
                "🟢"
                if o.op_type == OperationType.income
                else "🔴" if o.op_type == OperationType.expense else "🛡"
            )
            who = ""
            if is_owner:
                created_by = getattr(o, "created_by", None)
                who = (
                    getattr(created_by, "name", None)
                    or f"#{getattr(o, 'created_by_id', '—')}"
                ).strip()
            cat = getattr(getattr(o, "category", None), "name", None) or "—"
            comm = (getattr(o, "comment", None) or "").strip()

            if is_owner:
                base = f"{icon}{who} {o.amount} {cat}"
            else:
                base = f"{icon}{o.amount} {cat}"

            if comm:
                base += f' "{comm}"'
            lines.append(base)
        lines.append("")

    return "\n".join(lines).strip()


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

    # Баланс можно оставить (коротко)
    bal_text = await render_balance_message(repo)

    # Заголовок — компактный (как ты хочешь)
    header = (
        f"🟢 Доходы: {income_sum} ₽\n"
        f"🔴 Расходы: {expense_sum} ₽\n\n"
        f"{bal_text}\n\n"
    )

    is_owner = bool(user and user.role == UserRole.owner)
    body = format_ops_compact_by_day(ops, is_owner=is_owner)

    # Защита от простыни в чат: ограничим длину сообщения по строкам
    lines = body.splitlines()
    MAX_LINES = 80
    if len(lines) > MAX_LINES:
        body = "\n".join(lines[:MAX_LINES]).rstrip()
        body += "\n\n…Операций много. Для полного списка используйте CSV."

    # Примечание по области видимости
    if not is_owner:
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
    if not await require_user_callback(callback, user, action="report_pick_kind"):
        return

    kind = callback.data.split(":", 1)[1]  # all/income/expense
    await state.update_data(report_kind=kind)

    kb = report_period_inline(prefix="rp").as_markup()
    await callback.message.answer("Выберите период:", reply_markup=kb)
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("rp:"))
async def report_pick_period(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    user: User | None,
):
    if not await require_user_callback(callback, user, action="report_pick_period"):
        return

    repo = Repo(session)

    period = callback.data.split(":", 1)[1]  # 1/3/7/custom
    data = await state.get_data()
    kind = data.get("report_kind", "all")

    # 1) Кастомный период — переходим в FSM ввода дат (дальше CSV в report_custom_end)
    if period == "custom":
        await state.set_state(ReportCustomPeriod.start_date)
        await callback.message.answer("Введите дату начала (ДД.ММ.ГГГГ):")
        await callback.answer()
        return

    # 2) Быстрые пресеты 1/3/7 — делаем компактный отчёт текстом
    try:
        days = int(period)
    except ValueError:
        await callback.answer("Неизвестный период.", show_alert=True)
        return

    if days not in (1, 3, 7):
        await callback.answer(
            "Доступны пресеты: 1/3/7 дней или свой период.", show_alert=True
        )
        return

    start_msk, end_msk = _period_from_days_msk(days)

    text, ops = await _generate_report_text(repo, user, kind, start_msk, end_msk)

    # last_report сохраняем для ВСЕХ (нужно для CSV-кнопки)
    await state.update_data(
        last_report={
            "kind": kind,
            "start_utc": _to_utc(start_msk).isoformat(),
            "end_utc": _to_utc(end_msk).isoformat(),
        }
    )

    kb = owner_export_inline(
        prefix="re"
    ).as_markup()  # можно переименовать потом, но ок
    await callback.message.answer(text, reply_markup=kb)

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
        datetime.strptime(raw, "%d.%m.%Y")
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

    op_types = _op_types_from_kind(kind)
    created_by_id = _scope_created_by_id(user)

    ops = await repo.list_operations_filtered(
        op_types=op_types,
        start=_to_utc(start_msk),
        end=_to_utc(end_msk),
        created_by_id=created_by_id,
    )

    path = export_operations_csv(ops)
    await message.answer_document(
        FSInputFile(path, filename="report.csv"),
        caption="📄 CSV-отчёт за выбранный период (открывается в Excel).",
    )

    audit.info(
        "report.export.csv | tg_id=%s | role=%s | kind=%s | period=custom | ops=%s",
        message.from_user.id,
        user.role.value,
        kind,
        len(ops),
    )

    await state.clear()
    return


@router.callback_query(lambda c: c.data == "re:csv")
async def report_export_csv(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext, user: User | None
):
    if not await require_user_callback(callback, user, action="report_export_csv"):
        return

    repo = Repo(session)

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
    created_by_id = _scope_created_by_id(user)  # worker/viewer -> свои, owner -> все

    ops = await repo.list_operations_filtered(
        op_types=op_types,
        start=start,
        end=end,
        created_by_id=created_by_id,
    )

    path = export_operations_csv(ops)
    await callback.message.answer_document(
        FSInputFile(path, filename="report.csv"),
        caption="📄 CSV-отчёт (открывается в Excel).",
    )

    audit.info(
        "report.export.csv | tg_id=%s | role=%s | kind=%s | ops=%s",
        callback.from_user.id,
        user.role.value,
        kind,
        len(ops),
    )
    await callback.answer("Готово")
