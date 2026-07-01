"""Тесты чистой логики: агрегация позиций, парсинг новостей, форматирование."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import Database
from src.services.news import _parse_rss, keywords_for
from src.utils import fmt_money, fmt_pct


def test_positions_average_and_realized():
    with tempfile.TemporaryDirectory() as d:
        db = Database(os.path.join(d, "t.db"))
        uid = 1
        # Две покупки SBER по разной цене → средняя 250
        db.add_trade(uid, "SBER", "BUY", 10, 200, fee=0, date="2024-01-01")
        db.add_trade(uid, "SBER", "BUY", 10, 300, fee=0, date="2024-02-01")
        # Продажа 5 по 400 → фиксируем (400-250)*5 = 750
        db.add_trade(uid, "SBER", "SELL", 5, 400, fee=0, date="2024-03-01")

        pos = {p.ticker: p for p in db.positions(uid)}["SBER"]
        assert pos.quantity == 15, pos.quantity
        assert abs(pos.avg_price - 250) < 1e-6, pos.avg_price
        assert abs(pos.realized_pnl - 750) < 1e-6, pos.realized_pnl
        assert abs(pos.invested - 250 * 15) < 1e-6, pos.invested
        print("✓ positions: avg=250, realized=750, qty=15")


def test_tickers_union():
    with tempfile.TemporaryDirectory() as d:
        db = Database(os.path.join(d, "t.db"))
        db.add_trade(2, "GAZP", "BUY", 1, 100)
        db.add_watch(2, "LKOH")
        assert db.tickers(2) == ["GAZP", "LKOH"], db.tickers(2)
        print("✓ tickers union of trades + watchlist")


def test_rss_parsing():
    sample = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>Сбербанк отчитался о рекордной прибыли</title>
        <description>&lt;p&gt;Прибыль выросла&lt;/p&gt;</description>
        <link>https://example.com/1</link>
        <pubDate>Mon, 01 Jul 2024 09:30:00 +0300</pubDate>
      </item>
      <item><title>Газпром сократил экспорт</title></item>
    </channel></rss>""".encode("utf-8")
    items = _parse_rss("Тест", sample)
    assert len(items) == 2, len(items)
    assert items[0].title == "Сбербанк отчитался о рекордной прибыли"
    assert items[0].summary == "Прибыль выросла"
    assert items[0].published is not None
    print("✓ RSS parsing: 2 items, HTML stripped, date parsed")


def test_keywords():
    assert "сбербанк" in keywords_for("SBER")
    # неизвестный тикер → берём название с MOEX
    kw = keywords_for("XXXX", "Компания Пример")
    assert any("компания" in w for w in kw), kw
    print("✓ keywords: curated + MOEX name fallback")


def test_formatting():
    assert fmt_money(1234567.5) == "1 234 567.50 ₽", fmt_money(1234567.5)
    assert fmt_money(-100, "$") == "-100.00 $"
    assert fmt_pct(5.5) == "+5.50%"
    assert fmt_pct(-2) == "-2.00%"
    print("✓ formatting: money & percent")


if __name__ == "__main__":
    test_positions_average_and_realized()
    test_tickers_union()
    test_rss_parsing()
    test_keywords()
    test_formatting()
    print("\nВсе тесты пройдены ✅")
