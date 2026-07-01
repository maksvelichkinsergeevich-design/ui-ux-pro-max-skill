"""Тесты чистой логики: агрегация позиций, парсинг новостей, форматирование."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date

from src.database import Database, Trade
from src.services import charts
from src.services.analytics import (
    CandidateMetrics,
    composite_score,
    dividend_yield_pct,
    momentum_pct,
    rank_by_score,
)
from src.services.moex import Dividend
from src.services.news import _parse_rss, keywords_for
from src.services.portfolio_io import parse_trades_csv, trades_to_csv
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


def test_momentum():
    closes = [(f"2024-01-{i:02d}", 100 + i) for i in range(1, 22)]  # 101..121
    # моментум за 20 шагов: (121-101)/101
    assert abs(momentum_pct(closes, 20) - (121 - 101) / 101 * 100) < 1e-6
    assert momentum_pct([], 20) is None
    assert momentum_pct([("d", 100.0)], 20) is None
    print("✓ momentum")


def test_dividend_yield():
    today = date(2024, 7, 1)
    divs = [
        Dividend("SBER", 20.0, "RUB", "2024-05-01"),   # в пределах года
        Dividend("SBER", 10.0, "RUB", "2022-01-01"),   # старый, не считается
    ]
    y = dividend_yield_pct(divs, price=250.0, today=today)
    assert abs(y - 20.0 / 250.0 * 100) < 1e-6, y
    assert dividend_yield_pct(divs, price=None, today=today) is None
    print("✓ dividend yield (trailing 12m)")


def test_ranking():
    a = CandidateMetrics("A", "A", 100, 0, mom_1m=1, mom_3m=1, div_yield=10, next_dividend="")
    b = CandidateMetrics("B", "B", 100, 0, mom_1m=1, mom_3m=1, div_yield=1, next_dividend="")
    ranked = rank_by_score([b, a])
    assert ranked[0].ticker == "A", [m.ticker for m in ranked]
    assert composite_score(a) > composite_score(b)
    print("✓ composite score & ranking")


def test_csv_roundtrip_and_broker_import():
    trades = [Trade(1, 1, "SBER", "BUY", 10, 250.5, 5, "2024-01-01", "note")]
    csv_text = trades_to_csv(trades)
    assert "SBER" in csv_text and "ticker" in csv_text
    # русские заголовки + запятая как десятичный разделитель + разделитель ';'
    broker = "Тикер;Операция;Количество;Цена;Комиссия;Дата\nGAZP;Покупка;10;150,5;3;2024-02-01\nLKOH;Продажа;2;7000;10;2024-03-01"
    res = parse_trades_csv(broker)
    assert res.errors == [], res.errors
    assert len(res.trades) == 2, res.trades
    assert res.trades[0]["ticker"] == "GAZP" and res.trades[0]["side"] == "BUY"
    assert abs(res.trades[0]["price"] - 150.5) < 1e-6
    assert res.trades[1]["side"] == "SELL"
    print("✓ CSV export + broker-style import (RU headers, ';', decimal comma)")


def test_charts():
    pos = [charts.ChartPosition("SBER", 1000, 200), charts.ChartPosition("GAZP", 500, -50)]
    alloc = charts.allocation_chart(pos)
    pnl = charts.pnl_chart(pos)
    assert alloc and alloc.getvalue()[:8].startswith(b"\x89PNG"), "allocation not PNG"
    assert pnl and pnl.getvalue()[:8].startswith(b"\x89PNG"), "pnl not PNG"
    assert charts.allocation_chart([]) is None
    print("✓ charts render valid PNG")


if __name__ == "__main__":
    test_positions_average_and_realized()
    test_tickers_union()
    test_rss_parsing()
    test_keywords()
    test_formatting()
    test_momentum()
    test_dividend_yield()
    test_ranking()
    test_csv_roundtrip_and_broker_import()
    test_charts()
    print("\nВсе тесты пройдены ✅")
