#!/usr/bin/env python3
"""Первичная инициализация: БД, администратор, обновление расписания."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime

from app import config
from app.models import Session, User, init_db


def get_or_create_admin():
    """Создать/обновить первого администратора."""
    session = Session()
    try:
        user = session.query(User).filter(User.username == config.ADMIN_USERNAME).first()
        if user is None:
            user = User(
                telegram_id=config.ADMIN_TELEGRAM_ID,
                username=config.ADMIN_USERNAME,
                role='admin',
                created_at=datetime.now(),
                is_active=True,
            )
            user.set_password(config.ADMIN_PASSWORD)
            session.add(user)
            session.commit()
            print(f'✅ Админ создан: {config.ADMIN_USERNAME} / {config.ADMIN_PASSWORD}')
        else:
            user.role = 'admin'
            user.is_active = True
            if not user.password_hash:
                user.set_password(config.ADMIN_PASSWORD)
                session.commit()
                print(f'✅ Админу {config.ADMIN_USERNAME} установлен пароль: {config.ADMIN_PASSWORD}')
            else:
                print(f'ℹ️  Админ уже есть: {config.ADMIN_USERNAME}')
    finally:
        session.close()


def main():
    print('🚀 Инициализация...')
    os.makedirs('data', exist_ok=True)
    init_db()
    print('✅ База данных готова')

    get_or_create_admin()

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
