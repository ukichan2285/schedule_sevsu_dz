#!/usr/bin/env python3
"""Первичная инициализация: БД, администратор, обновление расписания."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime

from app import config
from app.models import init_db, ensure_admin


def main():
    print('🚀 Инициализация...')
    os.makedirs('data', exist_ok=True)
    init_db()
    print('✅ База данных готова')

    ensure_admin()

    # Пробуем сразу подтянуть расписание
    try:
        from app.updater import run_update
        print('🔄 Обновление расписания...')
        res = run_update()
        if res.get('ok'):
            print(f"✅ Расписание: +{res['added']} / −{res['removed']} (всего {res['total']})")
        else:
            print(f"⚠️  Расписание не обновлено: {res.get('error')}")
    except Exception as e:  # noqa: BLE001
        print(f'⚠️  Ошибка обновления: {e}')

    print('\nГотово!')
    print('  Веб-сайт:      python run_server.py')
    print('  Telegram-бот:  python start_bot.py')
    print('  Автообновление: python start_scheduler.py')


if __name__ == '__main__':
    main()
