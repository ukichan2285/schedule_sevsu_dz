#!/usr/bin/env python3
"""Первичная инициализация: БД, администратор, обновление расписания."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime

from app.models import Session, User, init_db


def get_or_create_admin(telegram_id, username):
    session = Session()
    try:
        user = session.query(User).filter(User.telegram_id == telegram_id).first()
        if user:
            print(f'ℹ️  Админ уже есть: @{user.username}')
            return
        session.add(User(
            telegram_id=telegram_id,
            username=username,
            role='admin',
            created_at=datetime.now(),
            is_active=True,
        ))
        session.commit()
        print(f'✅ Админ создан: @{username}')
    finally:
        session.close()


def main():
    print('🚀 Инициализация...')
    os.makedirs('data', exist_ok=True)
    init_db()
    print('✅ База данных готова')

    get_or_create_admin(8887484529, 'admin')

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
