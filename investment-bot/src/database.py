"""Хранилище портфеля и списка отслеживания на SQLite."""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Trade:
    id: int
    user_id: int
    ticker: str
    side: str  # BUY | SELL
    quantity: float
    price: float
    fee: float
    date: str
    note: str


@dataclass
class Position:
    """Агрегированная позиция по одному тикеру (метод средней цены)."""
    ticker: str
    quantity: float
    avg_price: float          # средняя цена покупки оставшихся бумаг
    invested: float           # вложено в текущий остаток (avg_price * quantity)
    realized_pnl: float       # зафиксированная прибыль/убыток по продажам
    total_fees: float


class Database:
    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id   INTEGER NOT NULL,
                    ticker    TEXT    NOT NULL,
                    side      TEXT    NOT NULL DEFAULT 'BUY',
                    quantity  REAL    NOT NULL,
                    price     REAL    NOT NULL,
                    fee       REAL    NOT NULL DEFAULT 0,
                    date      TEXT    NOT NULL,
                    note      TEXT    NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS watchlist (
                    user_id INTEGER NOT NULL,
                    ticker  TEXT    NOT NULL,
                    PRIMARY KEY (user_id, ticker)
                );
                CREATE INDEX IF NOT EXISTS idx_trades_user ON trades(user_id);
                """
            )

    # ---------- Сделки ----------
    def add_trade(
        self,
        user_id: int,
        ticker: str,
        side: str,
        quantity: float,
        price: float,
        fee: float = 0.0,
        date: str | None = None,
        note: str = "",
    ) -> int:
        date = date or datetime.now().strftime("%Y-%m-%d")
        with self._lock, self._conn:
            cur = self._conn.execute(
                """INSERT INTO trades (user_id, ticker, side, quantity, price, fee, date, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, ticker.upper(), side.upper(), quantity, price, fee, date, note),
            )
            return int(cur.lastrowid)

    def list_trades(self, user_id: int, ticker: str | None = None) -> list[Trade]:
        query = "SELECT * FROM trades WHERE user_id = ?"
        params: list = [user_id]
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker.upper())
        query += " ORDER BY date ASC, id ASC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_trade(r) for r in rows]

    def delete_trade(self, user_id: int, trade_id: int) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM trades WHERE user_id = ? AND id = ?", (user_id, trade_id)
            )
            return cur.rowcount > 0

    def tickers(self, user_id: int) -> list[str]:
        """Уникальные тикеры пользователя: из сделок + из списка отслеживания."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT ticker FROM trades WHERE user_id = ?
                   UNION SELECT ticker FROM watchlist WHERE user_id = ?
                   ORDER BY ticker""",
                (user_id, user_id),
            ).fetchall()
        return [r["ticker"] for r in rows]

    # ---------- Список отслеживания ----------
    def add_watch(self, user_id: int, ticker: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO watchlist (user_id, ticker) VALUES (?, ?)",
                (user_id, ticker.upper()),
            )

    def remove_watch(self, user_id: int, ticker: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
                (user_id, ticker.upper()),
            )
            return cur.rowcount > 0

    def list_watch(self, user_id: int) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY ticker",
                (user_id,),
            ).fetchall()
        return [r["ticker"] for r in rows]

    def all_user_ids(self) -> list[int]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT user_id FROM trades
                   UNION SELECT user_id FROM watchlist"""
            ).fetchall()
        return [r["user_id"] for r in rows]

    # ---------- Агрегация позиций ----------
    def positions(self, user_id: int) -> list[Position]:
        """Считает позиции методом средневзвешенной цены с учётом продаж."""
        trades = self.list_trades(user_id)
        acc: dict[str, dict] = {}
        for t in trades:
            p = acc.setdefault(
                t.ticker,
                {"qty": 0.0, "invested": 0.0, "realized": 0.0, "fees": 0.0},
            )
            p["fees"] += t.fee
            if t.side == "BUY":
                p["qty"] += t.quantity
                p["invested"] += t.quantity * t.price
            else:  # SELL
                if p["qty"] > 0:
                    avg = p["invested"] / p["qty"]
                    sold = min(t.quantity, p["qty"])
                    p["realized"] += (t.price - avg) * sold
                    p["invested"] -= avg * sold
                    p["qty"] -= sold
                else:
                    # продажа без учтённой покупки — считаем всю выручку прибылью
                    p["realized"] += t.price * t.quantity

        result: list[Position] = []
        for ticker, p in acc.items():
            qty = round(p["qty"], 6)
            avg = (p["invested"] / qty) if qty > 0 else 0.0
            result.append(
                Position(
                    ticker=ticker,
                    quantity=qty,
                    avg_price=avg,
                    invested=p["invested"] if qty > 0 else 0.0,
                    realized_pnl=p["realized"],
                    total_fees=p["fees"],
                )
            )
        result.sort(key=lambda x: x.ticker)
        return result

    @staticmethod
    def _row_to_trade(r: sqlite3.Row) -> Trade:
        return Trade(
            id=r["id"],
            user_id=r["user_id"],
            ticker=r["ticker"],
            side=r["side"],
            quantity=r["quantity"],
            price=r["price"],
            fee=r["fee"],
            date=r["date"],
            note=r["note"],
        )
