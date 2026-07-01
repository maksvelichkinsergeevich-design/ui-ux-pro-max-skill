"""Обработчики аналитики: котировки, дивиденды, новости, сводка."""
from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..services.moex import Dividend, MoexClient
from ..services.news import NewsClient, keywords_for
from ..services.summarizer import Summarizer
from ..utils import fmt_money, fmt_pct, pnl_emoji
from .common import get_config, get_db, restricted


@restricted
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("Формат: `/price SBER`", parse_mode=ParseMode.MARKDOWN)
        return
    ticker = context.args[0].upper()
    async with MoexClient() as moex:
        q = await moex.get_quote(ticker)
    if q is None or q.last is None:
        await update.effective_message.reply_text(f"Не нашёл котировку по «{ticker}» на TQBR.")
        return
    await update.effective_message.reply_text(
        f"{pnl_emoji(q.change_pct)} *{q.ticker}* — {q.name}\n"
        f"Цена: {fmt_money(q.last)} ({fmt_pct(q.change_pct)})\n"
        f"Обновлено: {q.updated or '—'}",
        parse_mode=ParseMode.MARKDOWN,
    )


def _format_dividends(ticker: str, divs: list[Dividend]) -> str:
    if not divs:
        return f"*{ticker}*: данных по дивидендам нет."
    from datetime import date
    today = date.today().isoformat()
    upcoming = [d for d in divs if d.registry_close >= today]
    recent = [d for d in divs if d.registry_close < today][-3:]
    lines = [f"💵 *{ticker}*"]
    if upcoming:
        lines.append("Предстоящие (закрытие реестра):")
        for d in upcoming[:3]:
            lines.append(f"  • {d.registry_close}: {fmt_money(d.value, d.currency)}")
    if recent:
        lines.append("Последние выплаты:")
        for d in reversed(recent):
            lines.append(f"  • {d.registry_close}: {fmt_money(d.value, d.currency)}")
    return "\n".join(lines)


@restricted
async def dividends(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_db(context)
    if context.args:
        tickers = [context.args[0].upper()]
    else:
        tickers = await asyncio.to_thread(db.tickers, update.effective_user.id)
    if not tickers:
        await update.effective_message.reply_text(
            "Укажите тикер (`/dividends SBER`) или добавьте бумаги в портфель.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = await update.effective_message.reply_text("💵 Собираю данные по дивидендам…")
    async with MoexClient() as moex:
        results = await asyncio.gather(*(moex.get_dividends(t) for t in tickers))
    blocks = [_format_dividends(t, divs) for t, divs in zip(tickers, results)]
    await msg.edit_text("\n\n".join(blocks), parse_mode=ParseMode.MARKDOWN)


async def _build_keywords(context: ContextTypes.DEFAULT_TYPE, tickers: list[str]) -> dict[str, list[str]]:
    """Ключевые слова для новостного поиска, с подтяжкой названий с MOEX."""
    async with MoexClient() as moex:
        quotes = await asyncio.gather(*(moex.get_quote(t) for t in tickers))
    return {
        t: keywords_for(t, q.name if q else None)
        for t, q in zip(tickers, quotes)
    }


async def _collect_and_summarize(
    context: ContextTypes.DEFAULT_TYPE, tickers: list[str]
) -> tuple[dict, str]:
    """Возвращает (новости по тикерам, ИИ-сводка или '')."""
    keywords = await _build_keywords(context, tickers)
    async with NewsClient() as news:
        news_by_ticker = await news.news_for(keywords, limit_per_ticker=5)

    config = get_config(context)
    summary = ""
    has_news = any(news_by_ticker.values())
    if has_news and config.ai_enabled:
        try:
            summarizer = Summarizer(config.anthropic_api_key, config.anthropic_model)
            summary = await summarizer.summarize(news_by_ticker)
        except Exception:
            summary = ""  # при сбое ИИ откатываемся на список новостей
    return news_by_ticker, summary


def _format_news_list(news_by_ticker: dict) -> str:
    blocks = []
    for ticker, items in news_by_ticker.items():
        if not items:
            continue
        lines = [f"📰 *{ticker}*"]
        for it in items:
            title = it.title
            if it.link:
                lines.append(f"  • [{title}]({it.link}) _{it.source} {it.published_str}_")
            else:
                lines.append(f"  • {title} _{it.source} {it.published_str}_")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


@restricted
async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_db(context)
    if context.args:
        tickers = [context.args[0].upper()]
    else:
        tickers = await asyncio.to_thread(db.tickers, update.effective_user.id)
    if not tickers:
        await update.effective_message.reply_text(
            "Укажите тикер (`/news SBER`) или добавьте бумаги в портфель / список наблюдения.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = await update.effective_message.reply_text("📰 Собираю и анализирую новости…")
    news_by_ticker, summary = await _collect_and_summarize(context, tickers)

    if not any(news_by_ticker.values()):
        await msg.edit_text("Свежих новостей по этим компаниям не нашёл.")
        return

    if summary:
        text = "🧠 *Сводка новостей*\n\n" + summary
        await msg.edit_text(text[:4096], parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        # ссылки на источники — отдельным сообщением
        links = _format_news_list(news_by_ticker)
        if links:
            await update.effective_message.reply_text(
                "🔗 *Источники*\n\n" + links[:4000],
                parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
            )
    else:
        text = _format_news_list(news_by_ticker)
        await msg.edit_text(text[:4096], parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


@restricted
async def digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Полная сводка: /portfolio + предстоящие дивиденды + новости."""
    db = get_db(context)
    user_id = update.effective_user.id
    tickers = await asyncio.to_thread(db.tickers, user_id)
    if not tickers:
        await update.effective_message.reply_text(
            "Пока нечего анализировать. Добавьте покупки (`/add`) или бумаги в наблюдение (`/watch`).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = await update.effective_message.reply_text("🗞 Формирую полную сводку…")
    text = await build_digest_text(context, user_id, tickers)
    await msg.edit_text(text[:4096], parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    news_by_ticker, summary = await _collect_and_summarize(context, tickers)
    if summary:
        await update.effective_message.reply_text(
            "🧠 *Сводка новостей*\n\n" + summary[:3900],
            parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
        )
    elif any(news_by_ticker.values()):
        await update.effective_message.reply_text(
            "📰 *Новости*\n\n" + _format_news_list(news_by_ticker)[:3900],
            parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
        )


async def build_digest_text(context: ContextTypes.DEFAULT_TYPE, user_id: int, tickers: list[str]) -> str:
    """Текстовая часть сводки: кратко портфель + ближайшие дивиденды."""
    from datetime import date
    db = get_db(context)
    positions = await asyncio.to_thread(db.positions, user_id)
    open_positions = [p for p in positions if p.quantity > 0]

    async with MoexClient() as moex:
        quotes = await asyncio.gather(*(moex.get_quote(p.ticker) for p in open_positions))
        div_lists = await asyncio.gather(*(moex.get_dividends(t) for t in tickers))

    lines = ["🗞 *Инвестиционная сводка*", ""]

    # Портфель
    if open_positions:
        invested = value = 0.0
        pos_lines = []
        for p, q in zip(open_positions, quotes):
            mp = q.last if q and q.last else p.avg_price
            v = mp * p.quantity
            invested += p.invested
            value += v
            pl = v - p.invested
            pos_lines.append(f"{pnl_emoji(pl)} {p.ticker}: {fmt_money(v)} ({fmt_pct((pl/p.invested*100) if p.invested else None)})")
        pl_total = value - invested
        lines.append("*Портфель*")
        lines.append(f"Оценка: {fmt_money(value)} | Вложено: {fmt_money(invested)}")
        lines.append(f"{pnl_emoji(pl_total)} P/L: {fmt_money(pl_total)} ({fmt_pct((pl_total/invested*100) if invested else None)})")
        lines += pos_lines
        lines.append("")

    # Ближайшие дивиденды
    today = date.today().isoformat()
    upcoming: list[Dividend] = []
    for divs in div_lists:
        upcoming += [d for d in divs if d.registry_close >= today]
    upcoming.sort(key=lambda d: d.registry_close)
    if upcoming:
        lines.append("*Ближайшие дивиденды*")
        for d in upcoming[:6]:
            lines.append(f"  • {d.registry_close} — {d.ticker}: {fmt_money(d.value, d.currency)}")
        lines.append("")

    lines.append("_Новости — ниже. Не является индивидуальной инвестиционной рекомендацией._")
    return "\n".join(lines)


# ---------- Список наблюдения ----------
@restricted
async def watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("Формат: `/watch SBER`", parse_mode=ParseMode.MARKDOWN)
        return
    db = get_db(context)
    ticker = context.args[0].upper()
    await asyncio.to_thread(db.add_watch, update.effective_user.id, ticker)
    await update.effective_message.reply_text(f"👁 Добавил *{ticker}* в наблюдение.", parse_mode=ParseMode.MARKDOWN)


@restricted
async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_message.reply_text("Формат: `/unwatch SBER`", parse_mode=ParseMode.MARKDOWN)
        return
    db = get_db(context)
    ok = await asyncio.to_thread(db.remove_watch, update.effective_user.id, context.args[0].upper())
    await update.effective_message.reply_text("Убрал из наблюдения." if ok else "Такой бумаги нет в списке.")


@restricted
async def watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_db(context)
    items = await asyncio.to_thread(db.list_watch, update.effective_user.id)
    if not items:
        await update.effective_message.reply_text("Список наблюдения пуст. Добавьте: `/watch SBER`",
                                                   parse_mode=ParseMode.MARKDOWN)
        return
    await update.effective_message.reply_text("👁 *Наблюдение:* " + ", ".join(items),
                                              parse_mode=ParseMode.MARKDOWN)
