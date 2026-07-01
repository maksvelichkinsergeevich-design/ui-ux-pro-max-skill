"""Генерация графиков портфеля в PNG (matplotlib, без GUI)."""
from __future__ import annotations

import io
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")  # headless-режим, без дисплея
import matplotlib.pyplot as plt  # noqa: E402


@dataclass
class ChartPosition:
    ticker: str
    value: float       # текущая рыночная стоимость позиции
    pnl: float         # бумажная прибыль/убыток


def allocation_chart(positions: list[ChartPosition]) -> io.BytesIO | None:
    """Круговая диаграмма распределения портфеля по стоимости."""
    data = [(p.ticker, p.value) for p in positions if p.value > 0]
    if not data:
        return None
    data.sort(key=lambda x: x[1], reverse=True)
    labels = [t for t, _ in data]
    sizes = [v for _, v in data]

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.pie(
        sizes, labels=labels, autopct="%1.1f%%", startangle=90,
        pctdistance=0.8, wedgeprops={"edgecolor": "white", "linewidth": 1},
    )
    ax.set_title("Распределение портфеля")
    ax.axis("equal")
    return _render(fig)


def pnl_chart(positions: list[ChartPosition]) -> io.BytesIO | None:
    """Горизонтальный бар-чарт бумажного P/L по позициям."""
    data = [(p.ticker, p.pnl) for p in positions]
    if not data:
        return None
    data.sort(key=lambda x: x[1])
    labels = [t for t, _ in data]
    values = [v for _, v in data]
    colors = ["#e74c3c" if v < 0 else "#2ecc71" for v in values]

    fig, ax = plt.subplots(figsize=(7, max(3, 0.5 * len(labels) + 1)))
    ax.barh(labels, values, color=colors)
    ax.axvline(0, color="#333", linewidth=0.8)
    ax.set_title("Бумажная прибыль/убыток по позициям, ₽")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    return _render(fig)


def _render(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf
