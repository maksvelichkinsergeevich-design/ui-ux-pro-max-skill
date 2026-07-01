#!/usr/bin/env python3
"""Точка входа для запуска инвестиционного Telegram-бота.

Использование:
    cp .env.example .env   # заполнить токены
    pip install -r requirements.txt
    python run.py
"""
from src.bot import main

if __name__ == "__main__":
    main()
