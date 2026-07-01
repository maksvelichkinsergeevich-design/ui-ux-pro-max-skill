"""ИИ-сводка по новостям через Claude API (Anthropic)."""
from __future__ import annotations

from .news import NewsItem

_SYSTEM = (
    "Ты — инвестиционный аналитик по рынку акций Московской биржи. "
    "На вход получаешь заголовки и выдержки новостей по компаниям из портфеля инвестора. "
    "Сделай краткую деловую сводку на русском языке. Для каждой компании:\n"
    "• что произошло (1–3 пункта, только по фактам из новостей);\n"
    "• как это может отразиться на бумаге (нейтрально, без инвестиционных рекомендаций).\n"
    "Если по компании новостей нет — не упоминай её. Не выдумывай факты, которых нет в тексте. "
    "Пиши сжато, по делу, используй маркированные списки. В конце добавь дисклеймер, "
    "что это не индивидуальная инвестиционная рекомендация."
)


class Summarizer:
    def __init__(self, api_key: str, model: str = "claude-sonnet-5") -> None:
        self._api_key = api_key
        self._model = model

    @staticmethod
    def _format_input(news_by_ticker: dict[str, list[NewsItem]]) -> str:
        blocks: list[str] = []
        for ticker, items in news_by_ticker.items():
            if not items:
                continue
            lines = [f"## {ticker}"]
            for it in items:
                line = f"- [{it.source} {it.published_str}] {it.title}"
                if it.summary:
                    line += f" — {it.summary[:300]}"
                lines.append(line)
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)

    async def rank_ideas(self, metrics_text: str, news_by_ticker: dict[str, list[NewsItem]]) -> str:
        """Ранжирует кандидатов и объясняет логику. Возвращает готовый текст."""
        news_block = self._format_input(news_by_ticker) or "Свежих новостей нет."
        system = (
            "Ты — инвестиционный аналитик по рынку акций/облигаций Московской биржи. "
            "На вход — таблица метрик по бумагам (цена, дневное изменение, моментум за 1 и 3 месяца, "
            "дивидендная доходность, ближайшие дивиденды) и свежие новости. "
            "Выбери 3–5 наиболее интересных к покупке идей. Для каждой:\n"
            "• тикер и короткий тезис (1–2 предложения);\n"
            "• на чём основан (динамика/дивиденды/новости — ссылайся на конкретные метрики и факты);\n"
            "• ключевой риск.\n"
            "Оценивай непредвзято, не выдумывай данные, которых нет во входе. "
            "Пиши сжато, маркированными списками, на русском. "
            "Обязательно заверши явным дисклеймером: это аналитический разбор, "
            "а не индивидуальная инвестиционная рекомендация."
        )
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self._api_key)
        try:
            resp = await client.messages.create(
                model=self._model,
                max_tokens=1800,
                system=system,
                messages=[{
                    "role": "user",
                    "content": f"Метрики по бумагам:\n{metrics_text}\n\nНовости:\n{news_block}",
                }],
            )
            parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
            return "\n".join(parts).strip()
        finally:
            await client.close()

    async def summarize(self, news_by_ticker: dict[str, list[NewsItem]]) -> str:
        payload = self._format_input(news_by_ticker)
        if not payload.strip():
            return ""

        # Импорт внутри метода, чтобы бот запускался и без установленного SDK.
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self._api_key)
        try:
            resp = await client.messages.create(
                model=self._model,
                max_tokens=1500,
                system=_SYSTEM,
                messages=[{
                    "role": "user",
                    "content": f"Сводка новостей по портфелю:\n\n{payload}",
                }],
            )
            parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
            return "\n".join(parts).strip()
        finally:
            await client.close()
