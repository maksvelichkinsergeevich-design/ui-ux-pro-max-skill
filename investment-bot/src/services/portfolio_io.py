"""Импорт/экспорт сделок в CSV (в т.ч. из брокерских отчётов)."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from ..database import Trade

# Канонический порядок колонок при экспорте.
EXPORT_HEADER = ["ticker", "side", "quantity", "price", "fee", "date", "note"]

# Возможные названия колонок в разных отчётах → каноническое имя.
_ALIASES: dict[str, str] = {
    "ticker": "ticker", "тикер": "ticker", "symbol": "ticker", "код": "ticker",
    "инструмент": "ticker", "secid": "ticker", "актив": "ticker",
    "side": "side", "тип": "side", "операция": "side", "направление": "side", "type": "side",
    "quantity": "quantity", "qty": "quantity", "кол-во": "quantity", "количество": "quantity",
    "лот": "quantity", "shares": "quantity", "объем": "quantity", "объём": "quantity",
    "price": "price", "цена": "price", "курс": "price",
    "fee": "fee", "комиссия": "fee", "commission": "fee", "сбор": "fee",
    "date": "date", "дата": "date", "время": "date", "datetime": "date",
    "note": "note", "примечание": "note", "комментарий": "note", "comment": "note",
}

_BUY_WORDS = {"buy", "b", "покупка", "купля", "покупк", "приобретение", "long"}
_SELL_WORDS = {"sell", "s", "продажа", "продаж", "short"}


@dataclass
class ImportResult:
    trades: list[dict]
    skipped: int
    errors: list[str]


def trades_to_csv(trades: list[Trade]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_HEADER)
    for t in trades:
        writer.writerow([t.ticker, t.side, t.quantity, t.price, t.fee, t.date, t.note])
    return buf.getvalue()


def _norm_side(raw: str) -> str:
    v = (raw or "").strip().lower()
    if v in _SELL_WORDS or any(v.startswith(w) for w in _SELL_WORDS):
        return "SELL"
    return "BUY"  # по умолчанию считаем покупкой


def _num(raw: str) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip().replace(" ", "").replace("\xa0", "").replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_trades_csv(text: str) -> ImportResult:
    """Разбирает CSV со сделками. Определяет разделитель и сопоставляет колонки.

    Обязательны: тикер, количество, цена. Остальное опционально.
    """
    text = text.lstrip("﻿")
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        return ImportResult([], 0, ["Файл пуст."])

    header = [_ALIASES.get(c.strip().lower(), "") for c in rows[0]]
    if "ticker" not in header:
        return ImportResult(
            [], 0,
            ["Не нашёл колонку с тикером. Заголовок должен содержать: "
             "ticker, quantity, price (или их русские аналоги)."],
        )

    trades: list[dict] = []
    skipped = 0
    errors: list[str] = []
    for i, row in enumerate(rows[1:], start=2):
        rec = {header[j]: row[j] for j in range(min(len(header), len(row))) if header[j]}
        ticker = (rec.get("ticker") or "").strip().upper()
        qty = _num(rec.get("quantity"))
        price = _num(rec.get("price"))
        if not ticker or qty is None or price is None or qty == 0:
            skipped += 1
            continue
        trades.append({
            "ticker": ticker,
            "side": _norm_side(rec.get("side", "")),
            "quantity": abs(qty),
            "price": price,
            "fee": _num(rec.get("fee")) or 0.0,
            "date": (rec.get("date") or "").strip()[:10] or None,
            "note": (rec.get("note") or "").strip(),
        })
    if not trades and not errors:
        errors.append("Не удалось распознать ни одной сделки.")
    return ImportResult(trades, skipped, errors)
