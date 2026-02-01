from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📈 Доход"), KeyboardButton(text="📉 Расход")],
            [KeyboardButton(text="🛡 Резерв"), KeyboardButton(text="📊 Отчёты")],
            [KeyboardButton(text="👥 Пользователи"), KeyboardButton(text="ℹ️ Баланс")],
        ],
        resize_keyboard=True,
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True
    )


def back_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Назад")]], resize_keyboard=True
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
            [KeyboardButton(text="📈 В резерв"), KeyboardButton(text="📉 Из резерва")],
            [KeyboardButton(text="🔙 Назад")],
        ],
        resize_keyboard=True,
    )


def reports_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📁 Скачать CSV"), KeyboardButton(text="🔙 Назад")],
        ],
        resize_keyboard=True,
    )


def users_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Список"), KeyboardButton(text="📈 Добавить")],
            [KeyboardButton(text="📉 Удалить"), KeyboardButton(text="🔙 Назад")],
        ],
        resize_keyboard=True,
    )
