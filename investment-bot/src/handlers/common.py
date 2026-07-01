"""Общие обработчики: /start, /help, проверка доступа."""
from __future__ import annotations

from functools import wraps
from typing import Awaitable, Callable

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..config import Config
from ..database import Database

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def get_db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def get_config(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.application.bot_data["config"]


def restricted(func: Handler) -> Handler:
    """Пускает только пользователей из ALLOWED_USER_IDS (если список задан)."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        config = get_config(context)
        user = update.effective_user
        if user is None or not config.is_allowed(user.id):
            if update.effective_message:
                await update.effective_message.reply_text(
                    f"⛔ Доступ ограничён. Ваш Telegram ID: {user.id if user else '—'}\n"
                    "Добавьте его в ALLOWED_USER_IDS в .env, чтобы пользоваться ботом."
                )
            return
        await func(update, context)
    return wrapper


HELP_TEXT = (
    "🤖 *Инвестиционный аналитик* — рынок MOEX\n\n"
    "*Портфель и сделки*\n"
    "`/add ТИКЕР кол-во цена [комиссия] [ГГГГ-ММ-ДД]` — записать покупку\n"
    "`/sell ТИКЕР кол-во цена [комиссия] [ГГГГ-ММ-ДД]` — записать продажу\n"
    "`/portfolio` — статистика портфеля с текущими ценами\n"
    "`/trades [ТИКЕР]` — список сделок\n"
    "`/del ID` — удалить сделку по номеру\n\n"
    "*Аналитика*\n"
    "`/price ТИКЕР` — текущая котировка\n"
    "`/dividends [ТИКЕР]` — дивиденды (по бумаге или по всему портфелю)\n"
    "`/news [ТИКЕР]` — сводка новостей (по компании или по портфелю)\n"
    "`/digest` — полная сводка: портфель + дивиденды + новости\n\n"
    "*Отслеживание новостей*\n"
    "`/watch ТИКЕР` — добавить компанию в наблюдение\n"
    "`/unwatch ТИКЕР` — убрать\n"
    "`/watchlist` — список наблюдаемых\n\n"
    "_Пример:_ `/add SBER 10 250.5 5`\n"
    "⚠️ Бот не даёт индивидуальных инвестиционных рекомендаций."
)


@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    name = user.first_name if user else "инвестор"
    await update.effective_message.reply_text(
        f"Привет, {name}! 👋\n\n"
        "Я помогу вести инвестиционный счёт по рынку MOEX: считать статистику по покупкам, "
        "следить за дивидендами и собирать сводку новостей по вашим компаниям.\n\n"
        "Начните с добавления покупки, например:\n"
        "`/add SBER 10 250.5`\n\n"
        "Полный список команд — /help",
        parse_mode=ParseMode.MARKDOWN,
    )


@restricted
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT, parse_mode=ParseMode.MARKDOWN)
