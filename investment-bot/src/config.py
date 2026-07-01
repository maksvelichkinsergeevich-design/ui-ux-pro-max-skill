"""Конфигурация бота из переменных окружения."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _parse_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                continue
    return ids


@dataclass(frozen=True)
class Config:
    telegram_token: str
    anthropic_api_key: str | None
    anthropic_model: str
    allowed_user_ids: set[int] = field(default_factory=set)
    database_path: str = "investment_bot.db"
    timezone: str = "Europe/Moscow"
    daily_digest_time: str | None = None

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    def is_allowed(self, user_id: int) -> bool:
        """Пустой список = доступ открыт всем."""
        return not self.allowed_user_ids or user_id in self.allowed_user_ids


def load_config() -> Config:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "Не задан TELEGRAM_BOT_TOKEN. Скопируйте .env.example в .env и заполните токен."
        )
    digest_time = os.getenv("DAILY_DIGEST_TIME", "").strip() or None
    return Config(
        telegram_token=token,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip() or None,
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5").strip(),
        allowed_user_ids=_parse_ids(os.getenv("ALLOWED_USER_IDS")),
        database_path=os.getenv("DATABASE_PATH", "investment_bot.db").strip(),
        timezone=os.getenv("TIMEZONE", "Europe/Moscow").strip(),
        daily_digest_time=digest_time,
    )
