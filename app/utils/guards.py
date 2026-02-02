from aiogram.types import Message, CallbackQuery
from app.models import User, UserRole
from app.keyboards import main_menu
import logging

logger = logging.getLogger(__name__)
audit = logging.getLogger("audit")


async def require_user(message: Message, user: User | None) -> bool:
    if not user or not user.is_active:
        audit.info(
            "auth.denied | tg_id=%s | reason=no_user_or_inactive", message.from_user.id
        )
        # можно молча return False, можно сообщение
        await message.answer("⛔ Доступ закрыт.")
        return False
    return True


async def require_user_callback(
    callback: CallbackQuery,
    user: User | None,
    action: str | None = None,
    alert: bool = True,
) -> bool:
    tg_id = callback.from_user.id if callback.from_user else None

    if not user or not user.is_active:
        audit.info(
            "auth.denied | tg_id=%s | action=%s | reason=no_user",
            tg_id,
            action,
        )
        await callback.answer("Доступ закрыт.", show_alert=alert)
        return False

    return True


async def require_owner(
    message: Message,
    user: User | None,
    action: str | None = None,
) -> bool:
    if not user or not user.is_active:
        audit.info(
            "auth.denied | tg_id=%s | action=%s | reason=no_user",
            message.from_user.id,
            action,
        )
        await message.answer("⛔ Доступ закрыт.")
        return False

    if user.role != UserRole.owner:
        audit.info(
            "auth.denied | tg_id=%s | user_id=%s | role=%s | action=%s",
            message.from_user.id,
            user.id,
            user.role.value,
            action,
        )
        await message.answer(
            "⛔ Только владелец.",
            reply_markup=main_menu(user.role),
        )
        return False

    return True


async def require_owner_callback(
    callback: CallbackQuery,
    user: User | None,
    action: str | None = None,
    alert: bool = True,
) -> bool:
    # у callback может не быть from_user (редко), но пусть будет защита
    tg_id = callback.from_user.id if callback.from_user else None

    if not user or not user.is_active:
        audit.info("auth.denied | tg_id=%s | action=%s | reason=no_user", tg_id, action)
        await callback.answer("Доступ закрыт.", show_alert=alert)
        return False

    if user.role != UserRole.owner:
        audit.info(
            "auth.denied | tg_id=%s | user_id=%s | role=%s | action=%s",
            tg_id,
            user.id,
            user.role.value,
            action,
        )
        await callback.answer("Только владелец.", show_alert=alert)
        return False

    return True
