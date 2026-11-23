# Сайт: вкладка «Сессия»

Изменение от 23.11.2026. Публичная страница `/session` с расписанием сессии,
дедлайнами по предметам и свободным Markdown-блоком «Общая информация».
Всё редактируется из админки, блок — ещё и из бота (`/session_info`).

Файлы: `app/models.py`, `app/routes.py`, `app/admin.py`, `app/markdown_render.py`,
`app/templates/session.html`, `app/templates/admin/{exams,deadlines,session_info}.html`,
`app/templates/admin/dashboard.html`, `app/bot.py`.

## Структура данных

| Таблица | Модель | Назначение |
|---|---|---|
| `exams` | `Exam` | экзамен/зачёт/диф. зачёт/консультация: предмет, тип, дата, время, аудитория, преподаватель, примечания |
| `deadlines` | `Deadline` | дедлайн: предмет, название, дата (`NULL` = «без срока»), время, примечания, `is_done` |
| `session_info` | `SessionInfo` | одна запись (id=1): Markdown-текст блока «Общая информация», `updated_by` — telegram id автора |
| `session_files` | `SessionFile` | вложения к экзаменам/дедлайнам: фото и PDF, `data` bytea (deferred), ровно один из `exam_id`/`deadline_id` |

Таблицы создаются `create_all` при старте; `migrate()` снимает `NOT NULL`
с `deadlines.due_date` на Postgres (SQLite не умеет `ALTER COLUMN` — свежие базы
создаются сразу nullable).

## Публичная страница `/session`

- **Расписание сессии** — карточки (`col-md-6 col-lg-4`), бейдж типа
  (экзамен → `danger`, зачёт/диф. зачёт → `primary`, консультация → `secondary`),
  дата, время, 📍 аудитория, 👤 преподаватель. Прошедшие — `opacity-50`
  в свёрнутом блоке.
- **Общая информация** — рендер `{{ info.text | md }}`, показывается только
  когда текст неполн; подпись «обновлено <дата>». Таблицы в обёртке `.md-info`
  (бордюры, полосатые строки, `overflow-x: auto` для узких экранов).
- **Дедлайны** — `list-group`: невыполненные сверху; просроченные (дата < сегодня
  и не сдано) — `list-group-item-danger`; выполненные — приглушены, зачёркнутое
  название; без даты — «без срока», без подсветки, в конце.
  Срок выводится как «до 15.01.2027» / «до 15.01, 18:00».
- Примечания экзаменов и дедлайнов рендерятся Markdown (`| md`, включая таблицы).
- Вложения — ссылки `би-иконка + имя + размер` на `/session/file/<id>`
  (раздача как `/homework/file/<id>`, 404 если нет).

Сортировка дедлайнов переносима между SQLite/Postgres:
`order_by(is_done, due_date.is_(None), due_date, due_time)` — NULL-даты
в конце в обеих СУБД.

## Админка

- `/admin/exams`, `/admin/deadlines` — списки + инлайн-формы (create/edit/delete
  с CSRF из сессии; у дедлайнов быстрый тумблер «сдано»).
- Дата сдачи дедлайна — необязательное поле (`_parse_date_optional`:
  пусто → `None`, неверный формат → flash).
- Вложения: multipart-формы, `<input type="file" name="files" multiple>`,
  разрешены `image/{jpeg,png,gif,webp}` и `application/pdf`, лимит 10 МБ
  (`_save_session_files` возвращает счётчик, неверные файлы пропускаются
  с flash). Удаление файла — POST `/admin/<exams|deadlines>/<id>/files/<fid>/delete`
  (проверка принадлежности + CSRF). Удаление записи каскадом сносит файлы
  (`cascade='all, delete-orphan'`).
- `/admin/session_info` — textarea для Markdown-блока (upsert записи id=1,
  `updated_by=None` при правке с сайта).
- Дашборд: карточки статистики и ссылки на все три раздела.

Вьюхи списков грузят файлы жадно (`joinedload`) — шаблоны читают `files`
после закрытия сессии, ленивая загрузка на detached-объекте кидает
`DetachedInstanceError` (поймано staging-тестом 23.11).

## Бот

- `/session_info` (алиас `sessioninfo`) — для админов и заполняющих ДЗ
  (проверка `_can_homework`): входит в режим ввода (привязан к `chat_id`,
  как режимы ДЗ/feedback), показывает превью текущего текста (300 симв.),
  следующее текстовое сообщение сохраняется в `SessionInfo` (upsert id=1,
  `updated_by` = telegram id). Отмена — `/cancel`.
- Markdown-рендер сайта: расширение `tables` + теги
  `table/thead/tbody/tr/th/td` в whitelist bleach (распространяется и на ДЗ).

## Грабли, учтённые заранее

- `DetachedInstanceError` при рендере после `commit()`/`close()`:
  `_get_session_info` делает `s.refresh(info)` после создания записи;
  вьюхи списков используют `joinedload`. Новые вьюхи с ленивыми связями
  в шаблонах — проверять по этому же шаблону.
- Postgres по умолчанию кладёт NULL последним в ASC, SQLite — первым:
  везде, где сортируем nullable-дату, добавлять `due_date.is_(None)`.

## Проверка

Staging на хосте (`~/.stage`, боевой `.env`): `create_app()` + `test_client` —
рендер `/session`, админ-страницы, multipart-загрузка PDF, отклонение `.exe`,
раздача файла, удаление, каскад, NULL-сортировка. Бэкапы деплоя:
`~/schedule_app/.backup/2026-11-23-{1139,1215,1236,1304}/`.
