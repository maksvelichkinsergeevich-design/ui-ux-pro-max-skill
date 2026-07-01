"""Вспомогательные функции форматирования."""
from __future__ import annotations


def fmt_money(value: float | None, currency: str = "₽") -> str:
    if value is None:
        return "—"
    sign = "-" if value < 0 else ""
    v = abs(value)
    # разряды пробелом, две значащие после запятой
    whole = f"{v:,.2f}".replace(",", " ")
    return f"{sign}{whole} {currency}".strip()


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def pnl_emoji(value: float | None) -> str:
    if value is None or value == 0:
        return "➖"
    return "🟢" if value > 0 else "🔴"
