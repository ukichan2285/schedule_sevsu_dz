#!/usr/bin/env python3
"""Telegram-бот как бесплатный Web Service на Render.

Render требует, чтобы web-сервис слушал $PORT, иначе контейнер считается
мёртвым. Поэтому поднимаем крошечный health-сервер, а бота крутим в основном
потоке (long polling).

Альтернатива: платный Background Worker + `python start_bot.py`.
"""
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import config
from app.bot import ScheduleBot
from app.models import Session, init_db, ensure_admin


class _Health(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, *args):  # заглушить шум health-сервера
        pass


def main():
    init_db()
    ensure_admin()

    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        raise SystemExit('❌ TELEGRAM_BOT_TOKEN не задан.')

    port = int(os.getenv('PORT', '10000'))
    health = HTTPServer(('0.0.0.0', port), _Health)
    threading.Thread(target=health.serve_forever, daemon=True).start()
    print(f'💚 Health-сервер слушает 0.0.0.0:{port}')

    bot = ScheduleBot(token, Session())
    bot.run()  # блокирующий polling; health-сервер живёт в фоновом потоке


if __name__ == '__main__':
    main()
