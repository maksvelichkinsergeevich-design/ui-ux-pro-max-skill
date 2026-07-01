"""Данные Московской биржи через публичное API ISS (без ключей).

Документация: https://iss.moex.com/iss/reference/
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import httpx

ISS = "https://iss.moex.com/iss"
_TIMEOUT = httpx.Timeout(10.0)
_HEADERS = {"User-Agent": "investment-bot/1.0"}


@dataclass
class Quote:
    ticker: str
    name: str
    last: float | None
    change_pct: float | None   # изменение к закрытию предыдущего дня, %
    currency: str
    board: str
    updated: str               # время котировки


@dataclass
class Dividend:
    ticker: str
    value: float
    currency: str
    registry_close: str        # дата закрытия реестра (YYYY-MM-DD)


@dataclass
class Bond:
    ticker: str                # SECID (напр. SU26238RMFS4)
    name: str                  # короткое название выпуска
    yield_pct: float | None    # доходность к погашению, % годовых
    price_pct: float | None    # цена, % от номинала
    coupon: float | None       # величина купона, ₽
    maturity: str              # дата погашения (YYYY-MM-DD)
    currency: str = "RUB"


def _to_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _rows(payload: dict, block: str) -> list[dict]:
    """Превращает блок ISS ({columns, data}) в список словарей."""
    section = payload.get(block, {})
    cols = section.get("columns", [])
    return [dict(zip(cols, row)) for row in section.get("data", [])]


class MoexClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "MoexClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def _get(self, url: str, params: dict | None = None) -> dict:
        assert self._client is not None
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_quote(self, ticker: str) -> Quote | None:
        """Текущая котировка по основному режиму торгов TQBR."""
        ticker = ticker.upper()
        url = f"{ISS}/engines/stock/markets/shares/boards/TQBR/securities/{ticker}.json"
        params = {
            "iss.meta": "off",
            "securities.columns": "SECID,SHORTNAME,CURRENCYID,PREVPRICE",
            "marketdata.columns": "SECID,LAST,LASTTOPREVPRICE,UPDATETIME",
        }
        try:
            data = await self._get(url, params)
        except httpx.HTTPError:
            return None

        sec = _rows(data, "securities")
        md = _rows(data, "marketdata")
        if not sec:
            return None

        s = sec[0]
        m = md[0] if md else {}
        last = m.get("LAST")
        change = m.get("LASTTOPREVPRICE")
        # Если торги закрыты, LAST может быть пустым — берём цену закрытия
        if last is None:
            last = s.get("PREVPRICE")
        return Quote(
            ticker=ticker,
            name=s.get("SHORTNAME") or ticker,
            last=last,
            change_pct=change,
            currency=s.get("CURRENCYID") or "RUB",
            board="TQBR",
            updated=m.get("UPDATETIME") or "",
        )

    async def get_dividends(self, ticker: str) -> list[Dividend]:
        """История и объявленные дивиденды по бумаге."""
        ticker = ticker.upper()
        url = f"{ISS}/securities/{ticker}/dividends.json"
        try:
            data = await self._get(url, {"iss.meta": "off"})
        except httpx.HTTPError:
            return []

        out: list[Dividend] = []
        for r in _rows(data, "dividends"):
            val = r.get("value")
            if val is None:
                continue
            out.append(
                Dividend(
                    ticker=ticker,
                    value=float(val),
                    currency=r.get("currencyid") or "RUB",
                    registry_close=str(r.get("registryclosedate") or ""),
                )
            )
        out.sort(key=lambda d: d.registry_close)
        return out

    async def upcoming_dividends(self, ticker: str) -> list[Dividend]:
        """Только предстоящие выплаты (дата закрытия реестра в будущем)."""
        today = date.today().isoformat()
        return [d for d in await self.get_dividends(ticker) if d.registry_close >= today]

    async def get_closes(self, ticker: str, days: int = 120) -> list[tuple[str, float]]:
        """Дневные цены закрытия за последние `days` дней: [(дата, close), ...]."""
        ticker = ticker.upper()
        frm = (date.today() - timedelta(days=days)).isoformat()
        url = f"{ISS}/engines/stock/markets/shares/boards/TQBR/securities/{ticker}/candles.json"
        params = {"iss.meta": "off", "from": frm, "interval": 24}
        try:
            data = await self._get(url, params)
        except httpx.HTTPError:
            return []
        out: list[tuple[str, float]] = []
        for r in _rows(data, "candles"):
            close = _to_float(r.get("close"))
            begin = str(r.get("begin") or "")[:10]
            if close is not None and begin:
                out.append((begin, close))
        out.sort(key=lambda x: x[0])
        return out

    async def get_bonds(self, board: str = "TQOB") -> list[Bond]:
        """Список облигаций с доходностью. TQOB — ОФЗ, TQCB — корпоративные."""
        url = f"{ISS}/engines/stock/markets/bonds/boards/{board}/securities.json"
        params = {
            "iss.meta": "off",
            "securities.columns": "SECID,SECNAME,MATDATE,COUPONVALUE,FACEUNIT",
            "marketdata.columns": "SECID,YIELD,LAST",
        }
        try:
            data = await self._get(url, params)
        except httpx.HTTPError:
            return []
        md = {r["SECID"]: r for r in _rows(data, "marketdata")}
        out: list[Bond] = []
        for s in _rows(data, "securities"):
            secid = s.get("SECID")
            m = md.get(secid, {})
            out.append(
                Bond(
                    ticker=secid,
                    name=s.get("SECNAME") or secid,
                    yield_pct=_to_float(m.get("YIELD")),
                    price_pct=_to_float(m.get("LAST")),
                    coupon=_to_float(s.get("COUPONVALUE")),
                    maturity=str(s.get("MATDATE") or ""),
                    currency=s.get("FACEUNIT") or "RUB",
                )
            )
        return out
