"""Сбор новостей из RSS-лент российских деловых СМИ и фильтрация по компаниям."""
from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx

_TIMEOUT = httpx.Timeout(10.0)
_HEADERS = {"User-Agent": "investment-bot/1.0"}

# RSS-ленты деловых СМИ по рынку РФ.
FEEDS: list[tuple[str, str]] = [
    ("РБК", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"),
    ("Финам", "https://www.finam.ru/analysis/conews/rsspoint/"),
    ("Коммерсантъ", "https://www.kommersant.ru/RSS/news.xml"),
    ("Интерфакс", "https://www.interfax.ru/rss.asp"),
]

# Ключевые слова для сопоставления новостей с тикером.
# Значение SHORTNAME с MOEX добавляется автоматически поверх этого списка.
TICKER_KEYWORDS: dict[str, list[str]] = {
    "SBER": ["сбербанк", "сбер"],
    "GAZP": ["газпром"],
    "LKOH": ["лукойл"],
    "GMKN": ["норникель", "норильский никель", "норникел"],
    "ROSN": ["роснефть"],
    "NVTK": ["новатэк", "новатек"],
    "YDEX": ["яндекс", "yandex"],
    "TCSG": ["тинькофф", "т-банк", "tcs"],
    "TATN": ["татнефть"],
    "MGNT": ["магнит"],
    "MTSS": ["мтс"],
    "VTBR": ["втб"],
    "ALRS": ["алроса"],
    "CHMF": ["северсталь"],
    "NLMK": ["нлмк", "новолипецкий"],
    "MAGN": ["ммк", "магнитогорский"],
    "PLZL": ["полюс"],
    "SNGS": ["сургутнефтегаз"],
    "MOEX": ["московская биржа", "мосбирж"],
    "PHOR": ["фосагро"],
    "RUAL": ["русал"],
    "AFLT": ["аэрофлот"],
    "OZON": ["озон", "ozon"],
    "VKCO": ["вконтакте", "vk ", "вк "],
    "POSI": ["позитив", "positive technolog"],
    "PIKK": ["пик"],
    "FIVE": ["x5", "пятёрочка", "перекрёсток"],
    "IRAO": ["интер рао"],
    "HYDR": ["русгидро"],
    "FEES": ["россети"],
    "SIBN": ["газпром нефть"],
}


@dataclass
class NewsItem:
    title: str
    summary: str
    link: str
    source: str
    published: datetime | None

    @property
    def published_str(self) -> str:
        if not self.published:
            return ""
        return self.published.astimezone().strftime("%d.%m %H:%M")


def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", "", text)          # снять HTML-теги
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _parse_rss(source: str, content: bytes) -> list[NewsItem]:
    items: list[NewsItem] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return items
    for item in root.iter("item"):
        title = _clean(item.findtext("title"))
        if not title:
            continue
        items.append(
            NewsItem(
                title=title,
                summary=_clean(item.findtext("description")),
                link=(item.findtext("link") or "").strip(),
                source=source,
                published=_parse_date(item.findtext("pubDate")),
            )
        )
    return items


class NewsClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> "NewsClient":
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True
            )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def _fetch_feed(self, source: str, url: str) -> list[NewsItem]:
        assert self._client is not None
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            return _parse_rss(source, resp.content)
        except (httpx.HTTPError, Exception):
            return []

    async def fetch_all(self) -> list[NewsItem]:
        """Все свежие новости из всех лент, отсортированные по дате."""
        results = await asyncio.gather(
            *(self._fetch_feed(src, url) for src, url in FEEDS)
        )
        merged: list[NewsItem] = [item for feed in results for item in feed]
        merged.sort(key=lambda n: n.published or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return merged

    async def news_for(
        self,
        keywords_by_ticker: dict[str, list[str]],
        limit_per_ticker: int = 5,
    ) -> dict[str, list[NewsItem]]:
        """Возвращает новости, сгруппированные по тикеру.

        keywords_by_ticker: {тикер: [ключевые слова в нижнем регистре]}.
        """
        all_news = await self.fetch_all()
        out: dict[str, list[NewsItem]] = {t: [] for t in keywords_by_ticker}
        for item in all_news:
            haystack = f"{item.title} {item.summary}".lower()
            for ticker, words in keywords_by_ticker.items():
                if len(out[ticker]) >= limit_per_ticker:
                    continue
                if any(w and w in haystack for w in words):
                    out[ticker].append(item)
        return out


def keywords_for(ticker: str, name: str | None = None) -> list[str]:
    """Собирает ключевые слова для тикера: курируемый список + название с MOEX."""
    ticker = ticker.upper()
    words = list(TICKER_KEYWORDS.get(ticker, []))
    if name:
        # Первое слово короткого названия обычно и есть узнаваемый бренд.
        base = re.split(r"[\s\-]", name.lower())[0]
        if len(base) >= 4 and base not in words:
            words.append(base)
    if not words:
        words.append(ticker.lower())
    return words
