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

# База данных: DATABASE_URL (Postgres/Render) имеет приоритет над SQLite-файлом.
# Если DATABASE_URL не задан — используется SQLite по пути SCHEDULE_DB_PATH
# (или data/schedule.db по умолчанию).
DATABASE_URL = _get('DATABASE_URL', '')
SCHEDULE_DB_PATH = _get('SCHEDULE_DB_PATH', '')

# Flask
SECRET_KEY = _get('SECRET_KEY', 'dev-secret-change-me')
# Для продакшена на Render/любом хостинге
PORT = int(_get('PORT', '5000'))
FLASK_DEBUG = _get('FLASK_DEBUG', '1') == '1'

# Telegram
TELEGRAM_BOT_TOKEN = _get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_ADMIN_ID = _get('TELEGRAM_ADMIN_ID', '')

# Прокси (если сервер не в России для сайта, или в России для Telegram)
# Пример: http://user:pass@host:port  или  socks5://host:port
SCHEDULE_PROXY = _get('SCHEDULE_PROXY', '')   # для запросов к schedule.sevsu.ru
TELEGRAM_PROXY = _get('TELEGRAM_PROXY', '')   # для Telegram Bot API

# Первый администратор (создаётся run.py)
ADMIN_USERNAME = _get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = _get('ADMIN_PASSWORD', 'admin123')
try:
    ADMIN_TELEGRAM_ID = int(_get('ADMIN_TELEGRAM_ID', '8887484529') or '8887484529')
except ValueError:
    ADMIN_TELEGRAM_ID = 8887484529
