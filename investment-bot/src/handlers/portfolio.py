"""Обработчики портфеля: покупки, продажи, статистика."""
from __future__ import annotations

import asyncio
from datetime import date

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..services.moex import MoexClient
from ..utils import fmt_money, fmt_pct, pnl_emoji
from .common import get_db, restricted


def _parse_trade_args(args: list[str]) -> tuple[str, float, float, float, str] | None:
    """Разбирает `ТИКЕР кол-во цена [комиссия] [дата]`."""
    if len(args) < 3:
        return None
    ticker = args[0].upper()
    try:
        qty = float(args[1].replace(",", "."))
        price = float(args[2].replace(",", "."))
    except ValueError:
        return None
    fee = 0.0
    trade_date = date.today().isoformat()
    if len(args) >= 4:
        try:
            fee = float(args[3].replace(",", "."))
        except ValueError:
            # возможно, это дата, а не комиссия
            trade_date = args[3]
    if len(args) >= 5:
        trade_date = args[4]
    return ticker, qty, price, fee, trade_date


async def _record(update: Update, context: ContextTypes.DEFAULT_TYPE, side: str) -> None:
    parsed = _parse_trade_args(context.args)
    verb = "покупки" if side == "BUY" else "продажи"
    if parsed is None:
        await update.effective_message.reply_text(
            f"Формат: `/{'add' if side == 'BUY' else 'sell'} ТИКЕР кол-во цена [комиссия] [ГГГГ-ММ-ДД]`\n"
            f"Например: `/{'add' if side == 'BUY' else 'sell'} SBER 10 250.5 5`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    ticker, qty, price, fee, trade_date = parsed
    db = get_db(context)
    trade_id = await asyncio.to_thread(
        db.add_trade, update.effective_user.id, ticker, side, qty, price, fee, trade_date
    )
    total = qty * price + (fee if side == "BUY" else -fee)
    emoji = "🟢" if side == "BUY" else "🔴"
    await update.effective_message.reply_text(
        f"{emoji} Записал сделку #{trade_id} ({verb}):\n"
        f"*{ticker}* — {qty:g} шт. по {fmt_money(price)}\n"
        f"Комиссия: {fmt_money(fee)}\n"
        f"Сумма: {fmt_money(total)}\n"
        f"Дата: {trade_date}",
        parse_mode=ParseMode.MARKDOWN,
    )


@restricted
async def add_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _record(update, context, "BUY")


@restricted
async def add_sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _record(update, context, "SELL")


@restricted
async def trades(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_db(context)
    ticker = context.args[0].upper() if context.args else None
    items = await asyncio.to_thread(db.list_trades, update.effective_user.id, ticker)
    if not items:
        await update.effective_message.reply_text("Сделок пока нет. Добавьте: `/add SBER 10 250.5`",
                                                   parse_mode=ParseMode.MARKDOWN)
        return
    lines = ["📒 *Сделки*" + (f" по {ticker}" if ticker else ""), ""]
    for t in items:
        sign = "🟢 покупка" if t.side == "BUY" else "🔴 продажа"
        lines.append(
            f"`#{t.id}` {t.date} {sign} *{t.ticker}* — {t.quantity:g} × {fmt_money(t.price)}"
            + (f", комиссия {fmt_money(t.fee)}" if t.fee else "")
        )
    lines.append("\nУдалить сделку: `/del ID`")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@restricted
async def delete_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Формат: `/del ID` (номер сделки из /trades)",
                                                   parse_mode=ParseMode.MARKDOWN)
        return
    db = get_db(context)
    ok = await asyncio.to_thread(db.delete_trade, update.effective_user.id, int(context.args[0]))
    await update.effective_message.reply_text("🗑 Сделка удалена." if ok else "Сделка не найдена.")


@restricted
async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = get_db(context)
    positions = await asyncio.to_thread(db.positions, update.effective_user.id)
    open_positions = [p for p in positions if p.quantity > 0]
    if not positions:
        await update.effective_message.reply_text(
            "Портфель пуст. Добавьте покупку: `/add SBER 10 250.5`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = await update.effective_message.reply_text("📊 Считаю статистику по текущим ценам…")

    # Текущие котировки для открытых позиций
    quotes = {}
    async with MoexClient() as moex:
        results = await asyncio.gather(*(moex.get_quote(p.ticker) for p in open_positions))
    for p, q in zip(open_positions, results):
        quotes[p.ticker] = q

    total_invested = 0.0
    total_value = 0.0
    total_realized = 0.0
    total_fees = 0.0
    lines = ["📊 *Портфель*", ""]

    for p in positions:
        total_realized += p.realized_pnl
        total_fees += p.total_fees
        if p.quantity <= 0:
            continue
        q = quotes.get(p.ticker)
        market_price = q.last if q and q.last else None
        value = market_price * p.quantity if market_price else None
        total_invested += p.invested
        if value is not None:
            total_value += value
            unreal = value - p.invested
            unreal_pct = (unreal / p.invested * 100) if p.invested else None
            lines.append(
                f"{pnl_emoji(unreal)} *{p.ticker}* — {p.quantity:g} шт.\n"
                f"   ср. цена {fmt_money(p.avg_price)} → тек. {fmt_money(market_price)}\n"
                f"   стоимость {fmt_money(value)} | P/L {fmt_money(unreal)} ({fmt_pct(unreal_pct)})"
            )
        else:
            total_value += p.invested
            lines.append(
                f"⚪️ *{p.ticker}* — {p.quantity:g} шт., ср. цена {fmt_money(p.avg_price)}\n"
                f"   (котировка недоступна)"
            )

    total_unreal = total_value - total_invested
    total_unreal_pct = (total_unreal / total_invested * 100) if total_invested else None

    lines += [
        "",
        "*Итого по открытым позициям*",
        f"Вложено: {fmt_money(total_invested)}",
        f"Оценка: {fmt_money(total_value)}",
        f"{pnl_emoji(total_unreal)} Бумажная прибыль: {fmt_money(total_unreal)} ({fmt_pct(total_unreal_pct)})",
    ]
    if abs(total_realized) > 1e-9:
        lines.append(f"💰 Зафиксировано (по продажам): {fmt_money(total_realized)}")
    if total_fees:
        lines.append(f"🧾 Всего комиссий: {fmt_money(total_fees)}")

    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
