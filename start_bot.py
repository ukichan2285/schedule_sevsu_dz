#!/usr/bin/env python3
"""Запуск Telegram-бота (long polling).

На Render (US-IP) Telegram доступен напрямую.
Если запускаете на РФ-сервере — задайте TELEGRAM_PROXY в .env.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import config
from app.bot import ScheduleBot
from app.models import Session, init_db, ensure_admin

init_db()
ensure_admin()

token = config.TELEGRAM_BOT_TOKEN
if not token:
    raise SystemExit('❌ TELEGRAM_BOT_TOKEN не задан. Укажите его в .env или в переменных окружения.')

bot = ScheduleBot(token, Session())
bot.run()
