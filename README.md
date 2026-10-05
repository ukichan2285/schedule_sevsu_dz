# Система отслеживания расписания занятий SEVSU

Прототип системы для отслеживания расписания занятий с сайта https://schedule.sevsu.ru с возможностью управления через Telegram бот.

## Возможности

- Парсинг расписания занятий с сайта SEVSU
- Анализ изменений в расписании
- Добавление колонки "Домашнее задание"
- Система аккаунтов с Telegram bot для управления
- Поддержка администраторов и обычных пользователей

## Технологии

- Python 3.14
- Flask 3.0.0
- SQLAlchemy 2.1.3
- SQLite (data/schedule.db)
- python-telegram-bot 22.8
- BeautifulSoup 4.12.3
- Requests 2.31.0

## Установка

1. Клонируйте репозиторий (или используйте текущую директорию)

2. Создайте виртуальное окружение и установите зависимости:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows

pip install -r requirements.txt
```

## Инициализация

1. Инициализируйте базу данных и создайте администратора:
```bash
source venv/bin/activate
python run.py
```

Скрипт создаст:
- Базу данных в `data/schedule.db`
- Администратора с username `admin`
- Таблицы для хранения расписания, ДЗ и изменений

## Настройка

### Telegram Bot

В файле `app/bot.py` настройте параметры:
```python
self.token = "ВАШ_ТОКЕН_БОТА"
self.admin_id = ВАШ_TELEGRAM_ID
```

В `start_bot.py` укажите таймзону:
```python
bot = ScheduleBot(
    token="ВАШ_ТОКЕН_БОТА",
    admin_id=ВАШ_TELEGRAM_ID,
    timezone="Europe/Moscow"
)
```

### Парсинг расписания

⚠️ **Важно:** сайт schedule.sevsu.ru — это SPA. Расписание грузится JavaScript'ом
через внутренний API, поэтому в HTML-коде страницы занятий нет. Обычный парсинг
HTML не сработает, даже с российского IP.

Рабочий способ — экспорт календаря `.ics`:
1. Откройте `https://schedule.sevsu.ru/groups/rs-s-26-1-o` (нужен российский IP)
2. ⚙ Настройки → «Получить ссылку на календарь»
3. Сохраните `.ics` в `data/schedule.ics`
4. Импортируйте:

```bash
source venv/bin/activate
python parse_now.py --input data/schedule.ics --reset
```

Полезные опции:
```bash
python parse_now.py --input data/schedule.ics --week-offset 1   # следующая неделя
python parse_now.py --input data/schedule.ics --all-weeks       # весь семестр
python parse_now.py --ip                                        # проверить внешний IP
```

Поддерживаются также `.json` (ответ API из DevTools → Network) и `.html`
(сохранённый DOM: Elements → Copy outerHTML).

### DDoS-Guard

Сайт https://schedule.sevsu.ru защищён DDoS-Guard и требует российский IP.
Экспорт `.ics` делается через браузер, поэтому напрямую парсеру ходить
на сайт не нужно.

## Использование

### Веб-сервер (Flask)

```bash
source venv/bin/activate
python run_server.py
```

Адрес: http://127.0.0.1:5000

Для публикации в интернете:
```bash
flask run --host=0.0.0.0 --port=80
```

### Автообновление расписания

```bash
source venv/bin/activate
python start_scheduler.py
```

Каждые `UPDATE_INTERVAL_MINUTES` минут (по умолчанию 30) скачивает `.ics`-календарь,
сравнивает с базой и записывает изменения в журнал.

### Админ-панель

Адрес входа: http://127.0.0.1:5000/login

Первый администратор создаётся `run.py`:
- логин — `ADMIN_USERNAME` (по умолчанию `admin`)
- пароль — `ADMIN_PASSWORD` (по умолчанию `admin123`) — **смените!**

Разделы (`/admin`):
- **Пользователи** (`/admin/users`) — создание аккаунтов, роли, пароли, блокировка
- **Домашние задания** (`/admin/homework`) — добавление/изменение/удаление ДЗ
- **Журнал изменений** (`/admin/changes`) — история автообновлений
- **Обновить расписание** — принудительное обновление

Пользователи с ролью `user` могут редактировать ДЗ, но не управлять пользователями.

### Запуск бота

```bash
source venv/bin/activate
python start_bot.py
```

### Команды Telegram бота

| Команда | Описание | Доступ |
|---------|----------|--------|
| `/start` | Приветственное сообщение | Все |
| `/help` | Справка по командам | Все |
| `/get_schedule` | Получить текущее расписание | Все |
| `/get_changes` | Получить последние изменения | Все |
| `/set_homework` | Добавить домашнее задание | Все |
| `/admin_add_user` | Добавить пользователя (админ) | Админ |
| `/admin_list_users` | Список пользователей (админ) | Админ |

## Структура проекта

```
shedule_sevsu/
├── app/
│   ├── __init__.py     # Создание Flask-приложения
│   ├── admin.py        # Админ-панель (вход, пользователи, ДЗ)
│   ├── bot.py          # Telegram бот
│   ├── config.py       # Конфигурация из .env
│   ├── ics_parser.py   # Разбор .ics-календаря
│   ├── models.py       # Модели SQLAlchemy
│   ├── routes.py       # Публичные страницы + JSON API
│   ├── updater.py      # Автообновление расписания
│   └── parser.py       # Старый HTML-парсер (не используется)
├── data/               # БД, скачанные .ics (не в git)
├── run.py              # Инициализация БД + админ
├── run_server.py       # Запуск сайта
├── start_bot.py        # Запуск Telegram-бота
├── start_scheduler.py  # Автообновление расписания
├── parse_now.py        # Ручной импорт .ics/.json/.html
├── git_push.sh         # Хелпер для push в GitHub
├── requirements.txt
└── README.md
```

## Модели данных

### User
- `id` - ID в БД
- `telegram_id` - Telegram ID
- `username` - Имя пользователя
- `role` - Роль (admin/user)
- `is_active` - Аккаунт активен

### Schedule
- `id` - ID в БД
- `date` - Дата занятия
- `day_of_week` - День недели
- `lesson_number` - Номер пары
- `subject` - Предмет
- `teacher` - Преподаватель
- `location` - Аудитория/Локация
- `lesson_type` - Тип занятия
- `hash` - Хеш для обнаружения изменений

### Homework
- `id` - ID в БД
- `schedule_id` - Ссылка на расписание
- `user_id` - Автор (ID)
- `text` - Текст ДЗ
- `created_at` - Дата создания
- `updated_at` - Дата обновления

### ScheduleChange
- `id` - ID в БД
- `old_hash` - Старый хеш
- `new_hash` - Новый хеш
- `changes` - Описание изменений
- `detected_at` - Дата обнаружения

## Проблемы и решения

### 1. 403 Forbidden при парсинге
**Причина:** DDoS-Guard защита требует российский IP.

**Решение:** Запустите парсер с сервера в России или используйте прокси.

### 2. Конфликт версий SQLAlchemy и Python 3.14
**Причина:** SQLAlchemy 2.0.25 несовместим с Python 3.14.

**Решение:** Обновлено до SQLAlchemy 2.1.3.

### 3. Несовместимость python-telegram-bot 20.7
**Причина:** Старая версия не поддерживает Python 3.14.

**Решение:** Обновлено до python-telegram-bot 22.8.

## Веб-интерфейс

Запуск веб-сервера:
```bash
source venv/bin/activate
python run_server.py
```

Адрес: http://127.0.0.1:5000

### Возможности сайта:
- Просмотр расписания на сегодня
- Просмотр расписания на неделю
- Добавление домашнего задания
- Обновление расписания

Для публикации в интернете используйте:
```bash
flask run --host=0.0.0.0 --port=80
```

## Дальнейшее развитие

1. Автоматический парсинг по расписанию (каждый день в 00:00)
2. Уведомления об изменениях расписания
3. Экспорт расписания в ICS для календаря
4. Голосования за замену преподавателей

## Лицензия

MIT License
