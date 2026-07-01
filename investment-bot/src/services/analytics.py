"""Аналитика для инвест-идей: моментум цены и дивидендная доходность.

Чистые расчётные функции вынесены отдельно и покрыты тестами (без обращений к сети).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta

from .moex import Dividend, MoexClient


def momentum_pct(closes: list[tuple[str, float]], lookback: int) -> float | None:
    """Изменение цены, % за последние `lookback` торговых дней.

    closes — отсортированный по дате список (дата, close). Берём последнюю цену
    и цену `lookback` шагов назад.
    """
    prices = [c for _, c in closes if c]
    if len(prices) < 2:
        return None
    last = prices[-1]
    idx = max(0, len(prices) - 1 - lookback)
    base = prices[idx]
    if not base:
        return None
    return (last - base) / base * 100


def dividend_yield_pct(
    dividends: list[Dividend], price: float | None, today: date | None = None
) -> float | None:
    """Дивидендная доходность за последние 12 мес., % к текущей цене."""
    if not price:
        return None
    today = today or date.today()
    year_ago = (today - timedelta(days=365)).isoformat()
    paid = sum(
        d.value for d in dividends
        if d.registry_close and year_ago <= d.registry_close <= today.isoformat()
    )
    if paid <= 0:
        return 0.0
    return paid / price * 100


@dataclass
class CandidateMetrics:
    ticker: str
    name: str
    price: float | None
    change_pct: float | None       # изменение за день
    mom_1m: float | None           # моментум ~1 мес (21 торговый день)
    mom_3m: float | None           # моментум ~3 мес (63 торговых дня)
    div_yield: float | None        # дивдоходность за 12 мес, %
    next_dividend: str             # ближайшая дата закрытия реестра или ""

    def as_row(self) -> str:
        def f(v, suffix="%"):
            return "—" if v is None else f"{v:+.1f}{suffix}" if suffix == "%" else f"{v:.2f}"
        return (
            f"{self.ticker} ({self.name}): цена {f(self.price, '')}, "
            f"день {f(self.change_pct)}, 1м {f(self.mom_1m)}, 3м {f(self.mom_3m)}, "
            f"дивдох {('—' if self.div_yield is None else f'{self.div_yield:.1f}%')}"
            + (f", ближ. дивиденд {self.next_dividend}" if self.next_dividend else "")
        )


def composite_score(m: "CandidateMetrics") -> float:
    """Эвристический балл для предварительного отбора и режима без ИИ.

    Совмещает среднесрочный моментум и дивдоходность. Чисто справочный ориентир.
    """
    score = 0.0
    if m.mom_3m is not None:
        score += m.mom_3m * 0.5
    if m.mom_1m is not None:
        score += m.mom_1m * 0.3
    if m.div_yield is not None:
        score += m.div_yield * 1.0
    return score


def rank_by_score(candidates: list["CandidateMetrics"]) -> list["CandidateMetrics"]:
    return sorted(candidates, key=composite_score, reverse=True)


async def _metrics_for(moex: MoexClient, ticker: str) -> CandidateMetrics | None:
    quote, closes, divs = await asyncio.gather(
        moex.get_quote(ticker),
        moex.get_closes(ticker, days=120),
        moex.get_dividends(ticker),
    )
    if quote is None:
        return None
    price = quote.last
    today = date.today().isoformat()
    upcoming = [d.registry_close for d in divs if d.registry_close >= today]
    return CandidateMetrics(
        ticker=ticker,
        name=quote.name,
        price=price,
        change_pct=quote.change_pct,
        mom_1m=momentum_pct(closes, 21),
        mom_3m=momentum_pct(closes, 63),
        div_yield=dividend_yield_pct(divs, price),
        next_dividend=min(upcoming) if upcoming else "",
    )


async def screen(moex: MoexClient, tickers: list[str]) -> list[CandidateMetrics]:
    """Собирает метрики по списку тикеров (параллельно)."""
    results = await asyncio.gather(*(_metrics_for(moex, t) for t in tickers))
    return [m for m in results if m is not None]
