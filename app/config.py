"""Конфигурация приложения. Значения берутся из .env (если есть)."""
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get(name, default=''):
    return os.getenv(name, default)


# Ссылка на .ics-календарь группы (из настроек сайта schedule.sevsu.ru)
SCHEDULE_ICS_URL = _get('SCHEDULE_ICS_URL')

# Учебная группа
DEFAULT_GROUP = _get('DEFAULT_GROUP', 'rs-s-26-1-o')

# Как часто обновлять расписание (минуты)
UPDATE_INTERVAL_MINUTES = int(_get('UPDATE_INTERVAL_MINUTES', '30'))

# На сколько недель вперёд хранить расписание
WEEKS_AHEAD = int(_get('WEEKS_AHEAD', '8'))

# Flask
SECRET_KEY = _get('SECRET_KEY', 'dev-secret-change-me')

# Telegram
TELEGRAM_BOT_TOKEN = _get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_ADMIN_ID = _get('TELEGRAM_ADMIN_ID', '')

# Первый администратор (создаётся run.py)
ADMIN_USERNAME = _get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = _get('ADMIN_PASSWORD', 'admin123')
ADMIN_TELEGRAM_ID = int(_get('ADMIN_TELEGRAM_ID', '8887484529'))
