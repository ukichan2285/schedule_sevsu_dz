# schedule_sevsu

Система отслеживания расписания занятий для учебной группы с сайта
[schedule.sevsu.ru](https://schedule.sevsu.ru): веб-сайт с расписанием, домашними
заданиями и админкой, а также Telegram-бот для заполнения ДЗ и обратной связи.

## Что умеет

- Показывает расписание на сайте (по дням и неделям) и отдаёт JSON API
- Автоматически обновляет расписание из `.ics`-календаря группы и отслеживает изменения
- Хранит домашние задания с Markdown-текстом и фото
- Telegram-бот: заполнение ДЗ админом (`/homework`), обратная связь (`/feedback`)
- Админ-панель: пользователи, ДЗ, пожелания, журнал изменений

## Стек

Python 3.12, Flask, SQLAlchemy, PostgreSQL, python-telegram-bot, gunicorn.

## Запуск

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # и заполните значения
python run.py          # создаёт таблицы и администратора
python run_server.py   # сайт
python start_bot.py    # Telegram-бот
```

Обновление расписания разово: `python update_once.py` (удобно запускать из cron).

## Конфигурация

Все настройки — в `.env` (шаблон: `.env.example`). Ключевые:

- `SCHEDULE_ICS_URL` — ссылка на `.ics`-календарь группы
- `DATABASE_URL` — строка подключения к PostgreSQL
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_ID` — бот и админ
- `SECRET_KEY` — секрет Flask

## Замечания

- `schedule.sevsu.ru` — SPA и отдаёт данные только с российских IP, поэтому
  обновление расписания нужно запускать с российского адреса.
- Секреты (`.env`, `.token`) в репозиторий не попадают.

## Лицензия

См. файл [LICENSE](LICENSE).
