from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from app.models import UserRole


def main_menu(role: UserRole | None = None) -> ReplyKeyboardMarkup:
    # Общие кнопки
    rows = [
        [KeyboardButton(text="🟢 Доход"), KeyboardButton(text="🔴 Расход")],
        [KeyboardButton(text="🛡 Резерв"), KeyboardButton(text="ℹ️ Баланс")],
    ]

    # Только владелец видит админку и "полные" отчёты
    if role == UserRole.owner:
        rows.insert(
            1,
            [KeyboardButton(text="📊 Отчёты"), KeyboardButton(text="👥 Пользователи")],
        )
    else:
        # Работнику/наблюдателю можно оставить быстрый отчёт
        rows.insert(1, [KeyboardButton(text="📊 Отчёты")])

    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True
    )


def back_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Назад")]], resize_keyboard=True
    )


def confirm_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Подтвердить"), KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True,
    )


def reserve_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🟢 В резерв"), KeyboardButton(text="🔴 Из резерва")],
            [KeyboardButton(text="Назад")],
        ],
        resize_keyboard=True,
    )


def reports_menu() -> ReplyKeyboardMarkup:
    # Если CSV убираем — можно потом удалить эту клаву вообще
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Назад")],
        ],
        resize_keyboard=True,
    )


def users_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Список"), KeyboardButton(text="🟢 Добавить")],
            [KeyboardButton(text="🔴 Удалить"), KeyboardButton(text="Назад")],
        ],
        resize_keyboard=True,
    )
