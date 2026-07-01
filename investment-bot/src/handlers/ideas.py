"""Инвест-идеи: подбор акций и облигаций по динамике, дивидендам и новостям."""
from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..services import analytics
from ..services.moex import MoexClient
from ..services.news import TICKER_KEYWORDS, NewsClient, keywords_for
from ..services.summarizer import Summarizer
from ..utils import fmt_pct
from .common import get_config, get_db, restricted

# Ликвидная вселенная «голубых фишек» для скрининга по умолчанию.
DEFAULT_UNIVERSE = list(TICKER_KEYWORDS.keys())
SHORTLIST_SIZE = 12


@restricted
async def ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/ideas [ТИКЕР ...]` — подбор идей к покупке.

    Без аргументов скринит ликвидные голубые фишки; можно передать свой список.
    """
    universe = [a.upper() for a in context.args] if context.args else DEFAULT_UNIVERSE
    msg = await update.effective_message.reply_text(
        "🔎 Анализирую динамику, дивиденды и новости… это займёт несколько секунд."
    )

    async with MoexClient() as moex:
        metrics = await analytics.screen(moex, universe)
    if not metrics:
        await msg.edit_text("Не удалось получить данные по бумагам. Попробуйте позже.")
        return

    ranked = analytics.rank_by_score(metrics)
    shortlist = ranked[:SHORTLIST_SIZE]

    config = get_config(context)
    if config.ai_enabled:
        # Новости только по шорт-листу — экономим запросы и токены.
        kw = {m.ticker: keywords_for(m.ticker, m.name) for m in shortlist}
        async with NewsClient() as news:
            news_by_ticker = await news.news_for(kw, limit_per_ticker=3)

        metrics_text = "\n".join(m.as_row() for m in shortlist)
        try:
            summarizer = Summarizer(config.anthropic_api_key, config.anthropic_model)
            answer = await summarizer.rank_ideas(metrics_text, news_by_ticker)
            await msg.edit_text(
                ("💡 *Инвест-идеи*\n\n" + answer)[:4096],
                parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True,
            )
            return
        except Exception:
            pass  # откат на эвристический список ниже

    # Режим без ИИ: эвристический рейтинг по моментуму + дивдоходности.
    lines = ["💡 *Идеи по динамике и дивидендам*",
             "_Эвристический скрининг (моментум + дивдоходность). "
             "Для умного разбора задайте ANTHROPIC_API_KEY._", ""]
    for i, m in enumerate(shortlist[:7], start=1):
        lines.append(
            f"{i}. *{m.ticker}* — {m.name}\n"
            f"   3м: {fmt_pct(m.mom_3m)} | 1м: {fmt_pct(m.mom_1m)} | "
            f"дивдох: {('—' if m.div_yield is None else f'{m.div_yield:.1f}%')}"
            + (f" | ближ. дивиденд {m.next_dividend}" if m.next_dividend else "")
        )
    lines.append("\n⚠️ Не является индивидуальной инвестиционной рекомендацией.")
    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                        disable_web_page_preview=True)


@restricted
async def bonds(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """`/bonds [corp]` — топ облигаций по доходности. По умолчанию ОФЗ (TQOB)."""
    corp = bool(context.args and context.args[0].lower() in {"corp", "корп", "tqcb"})
    board = "TQCB" if corp else "TQOB"
    title = "корпоративные облигации" if corp else "ОФЗ"

    msg = await update.effective_message.reply_text(f"💵 Собираю {title} по доходности…")
    async with MoexClient() as moex:
        items = await moex.get_bonds(board)

    # Отбрасываем бумаги без адекватной доходности/цены.
    valid = [b for b in items if b.yield_pct and 0 < b.yield_pct < 40 and b.price_pct]
    valid.sort(key=lambda b: b.yield_pct or 0, reverse=True)
    if not valid:
        await msg.edit_text("Не удалось получить данные по облигациям. Попробуйте позже.")
        return

    lines = [f"💵 *Топ {title} по доходности к погашению*", ""]
    for b in valid[:10]:
        lines.append(
            f"• *{b.ticker}* — {b.name[:34]}\n"
            f"   YTM ~{b.yield_pct:.2f}% | цена {b.price_pct:.1f}% номинала"
            + (f" | погашение {b.maturity}" if b.maturity else "")
        )
    lines.append("\n_Доходность указана по данным MOEX и может меняться. "
                 "Не является индивидуальной инвестиционной рекомендацией._")
    if not corp:
        lines.append("Корпоративные выпуски: `/bonds corp`")
    await msg.edit_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                        disable_web_page_preview=True)
