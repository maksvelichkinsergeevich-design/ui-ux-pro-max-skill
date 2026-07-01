"""Сборка и запуск Telegram-бота."""
from __future__ import annotations

import asyncio
import logging
from datetime import time as dtime
from zoneinfo import ZoneInfo

from telegram import BotCommand
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from .config import Config, load_config
from .database import Database
from .handlers import common, news, portfolio

logger = logging.getLogger(__name__)


async def _post_init(app: Application) -> None:
    """Регистрирует меню команд в интерфейсе Telegram."""
    await app.bot.set_my_commands([
        BotCommand("start", "Начало работы"),
        BotCommand("help", "Список команд"),
        BotCommand("add", "Записать покупку: ТИКЕР кол-во цена"),
        BotCommand("sell", "Записать продажу: ТИКЕР кол-во цена"),
        BotCommand("portfolio", "Статистика портфеля"),
        BotCommand("trades", "Список сделок"),
        BotCommand("del", "Удалить сделку по ID"),
        BotCommand("price", "Котировка: ТИКЕР"),
        BotCommand("dividends", "Дивиденды: ТИКЕР или по портфелю"),
        BotCommand("news", "Сводка новостей: ТИКЕР или по портфелю"),
        BotCommand("digest", "Полная сводка"),
        BotCommand("watch", "Наблюдать за компанией: ТИКЕР"),
        BotCommand("unwatch", "Убрать из наблюдения"),
        BotCommand("watchlist", "Список наблюдения"),
    ])


async def _daily_digest_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ежедневная рассылка сводки всем пользователям бота."""
    db: Database = context.application.bot_data["db"]
    user_ids = await asyncio.to_thread(db.all_user_ids)
    for user_id in user_ids:
        try:
            tickers = await asyncio.to_thread(db.tickers, user_id)
            if not tickers:
                continue
            text = await news.build_digest_text(context, user_id, tickers)
            await context.bot.send_message(
                chat_id=user_id, text=text[:4096],
                parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
            )
            news_by_ticker, summary = await news._collect_and_summarize(context, tickers)
            body = summary or news._format_news_list(news_by_ticker)
            if body:
                await context.bot.send_message(
                    chat_id=user_id, text=("🧠 *Сводка новостей*\n\n" + body)[:4096],
                    parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось отправить сводку пользователю %s: %s", user_id, exc)


def build_application(config: Config | None = None) -> Application:
    config = config or load_config()
    db = Database(config.database_path)

    app = Application.builder().token(config.telegram_token).post_init(_post_init).build()
    app.bot_data["config"] = config
    app.bot_data["db"] = db

    # Общие
    app.add_handler(CommandHandler("start", common.start))
    app.add_handler(CommandHandler("help", common.help_command))
    # Портфель
    app.add_handler(CommandHandler("add", portfolio.add_buy))
    app.add_handler(CommandHandler("sell", portfolio.add_sell))
    app.add_handler(CommandHandler("portfolio", portfolio.portfolio))
    app.add_handler(CommandHandler(["stats", "stat"], portfolio.portfolio))
    app.add_handler(CommandHandler("trades", portfolio.trades))
    app.add_handler(CommandHandler(["del", "delete"], portfolio.delete_trade))
    # Аналитика
    app.add_handler(CommandHandler("price", news.price))
    app.add_handler(CommandHandler(["dividends", "div"], news.dividends))
    app.add_handler(CommandHandler("news", news.news))
    app.add_handler(CommandHandler("digest", news.digest))
    # Наблюдение
    app.add_handler(CommandHandler("watch", news.watch))
    app.add_handler(CommandHandler("unwatch", news.unwatch))
    app.add_handler(CommandHandler("watchlist", news.watchlist))

    # Ежедневная сводка
    if config.daily_digest_time and app.job_queue is not None:
        try:
            hh, mm = map(int, config.daily_digest_time.split(":"))
            tz = ZoneInfo(config.timezone)
            app.job_queue.run_daily(_daily_digest_job, time=dtime(hh, mm, tzinfo=tz), name="daily_digest")
            logger.info("Ежедневная сводка запланирована на %s (%s)", config.daily_digest_time, config.timezone)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Не удалось запланировать ежедневную сводку: %s", exc)

    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    config = load_config()
    if not config.ai_enabled:
        logger.warning("ANTHROPIC_API_KEY не задан — сводки будут выводиться списком без ИИ-резюме.")
    app = build_application(config)
    logger.info("Бот запущен. Ожидаю сообщения…")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
