#!/usr/bin/env python3
"""Запуск веб-сервера.

Для разработки:  python run_server.py
Для продакшена:  gunicorn run_server:app --bind 0.0.0.0:$PORT
"""
import os

from app import create_app

# app создаётся на уровне модуля — это точка входа для gunicorn
app = create_app()


if __name__ == '__main__':
    port = int(os.getenv('PORT', '5000'))
    debug = os.getenv('FLASK_DEBUG', '1') == '1'
    host = os.getenv('HOST', '127.0.0.1' if debug else '0.0.0.0')

    print('🚀 Запуск веб-сервера...')
    print(f'🌐 Адрес: http://{host}:{port}')
    app.run(debug=debug, host=host, port=port)
