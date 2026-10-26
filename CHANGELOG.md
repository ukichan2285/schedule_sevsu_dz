# Изменения

## 2026-10-26

### Добавлено
- **Свой домен и HTTPS:** сайт доступен по `https://schedule-sevsu.ru/` с валидным
  сертификатом Let's Encrypt (`CN=schedule-sevsu.ru`), `http://` → 301 на https.
  Домен `schedule-sevsu.ru` зарегистрирован, NS → SprintHost, A-запись `141.8.192.31`.
- **Документация:**
  - `docs/https-domain.md` — как выдан домен и SSL, грабли с `X-Forwarded-Proto`, проверки, откат.
  - `docs/bot-homework-menu.md` — новый флоу заполнения ДЗ в боте.
- **Бот: меню ДЗ «предмет → дата»** вместо «неделя → день → пара»:
  - `/homework` → список предметов (только те, где есть практики);
  - пары предмета вперёд от сегодняшнего дня (до +8 недель) с датой, днём недели, номером,
    временем, подгруппой и пометками «сегодня»/«завтра»; `📝` — если ДЗ уже заполнено;
  - «📜 Прошедшие пары» — до 6 последних пар предмета, чтобы поправить старое ДЗ.

### Изменено
- `app/config.py` — флаг `HTTPS_ENABLED` (env, по умолчанию `0`).
- `app/__init__.py` — при `HTTPS_ENABLED=1`: `ProxyFix(x_proto=1, x_host=1)`,
  `PREFERRED_URL_SCHEME='https'`, `SESSION_COOKIE_SECURE`, `REMEMBER_COOKIE_SECURE`.
- `deploy/sprinthost/htaccess` — редирект на https по `X-Forwarded-Proto`, ACME-путь исключён,
  канонический редирект с Duck DNS-алиаса на основной домен.
- `.env.example` — задокументирована переменная `HTTPS_ENABLED`.
- `app/bot.py` — даты пар берутся из `Schedule.date`, лекции отфильтровываются `is_lecture()`;
  карточка ввода ДЗ (Markdown + фото, «✅ Готово», «🗑 Очистить») сохранена, кнопка возврата
  «« К датам» ведёт к списку дат предмета.
- `PLAN.md` (локальный, вне git) — этапы 6 и 7, структура проекта.

### Исправлено
- Бесконечный редирект http→https после включения SSL: перед Apache стоит openresty (nginx),
  TLS терминируется на нём, поэтому в Apache `%{HTTPS}` всегда `off` и `SERVER_PORT=80`.
  Условие заменено на `%{HTTP:X-Forwarded-Proto} !https`.
- Неразличимые кнопки пар у «Физической культуры» (подгруппы 1 и 2 с одинаковой датой и номером) —
  в подпись добавлена подгруппа.

### Удалено
- Старый флоу заполнения ДЗ в боте: `_weeks_with_lessons`, `_send_weeks`, callback-и
  `hw:weeks`, `hw:w:`, `hw:d:`, `hw:dayof:`, неиспользуемые `current_monday()` и импорт `fmt_week`.
- На хосте (вне git): ручной `acme.sh` (`~/.acme.sh`, `~/ssl`, cron-задача, строка в `~/.bashrc`)
  после перехода на собственный домен; Duck DNS-алиас больше не обслуживается.

### Коммиты
- `49b7d7c` — HTTPS: `HTTPS_ENABLED`, `ProxyFix`/secure-cookies, редирект по `X-Forwarded-Proto`.
- `abdfeae` — docs: домен и HTTPS.
- `a4d46d1` — бот: меню ДЗ «предмет → дата» + `docs/bot-homework-menu.md`.
