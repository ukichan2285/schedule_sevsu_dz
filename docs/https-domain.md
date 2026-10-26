# Домен и HTTPS: `schedule-sevsu.ru`

Запись о работах от 25–26.10.2026: выдача серверу домена и установка SSL-сертификата.
Дополняет `PLAN.md` (он в `.gitignore`, поэтому эта страница — отслеживаемый источник).

## 1. Итог

| Что | Значение |
|-----|----------|
| Домен | `schedule-sevsu.ru` (куплен, зона `.ru`) |
| NS | `ns1.sprinthost.ru`, `ns2.sprinthost.ru`, `ns3.sprinthost.net`, `ns4.sprinthost.net` |
| A-запись | `141.8.192.31` (SprintHost, сервер `modi`) |
| Сертификат | Let's Encrypt, `CN=schedule-sevsu.ru`, issuer `YR1`, установлен поддержкой SprintHost |
| Сайт по HTTPS | `https://schedule-sevsu.ru/` → 200, `ssl verify = 0` |
| HTTP | `http://schedule-sevsu.ru/*` → 301 на https |
| Тех-домен | `http://schedule-sevsu.ru.xsph.ru/` → 301 на основной домен (редирект панели) |

Проверено снаружи (после деплоя):

```
https://schedule-sevsu.ru/              200
http://schedule-sevsu.ru/               301 -> https://schedule-sevsu.ru/
http://schedule-sevsu.ru/week?w=2       301 -> https://schedule-sevsu.ru/week?w=2
https://schedule-sevsu.ru/week          200
https://schedule-sevsu.ru/api/schedule  200 (JSON с занятиями)
https://schedule-sevsu.ru/admin         302 -> /login (без сессии — так и должно быть)
https://schedule-sevsu.ru/login         200
```

`~/schedule_app/wsgi.log` — чисто, `OK db=***@localhost:5432/broarik843_schedule-sevsu`.

## 2. Изменения в коде

| Файл | Что сделано |
|------|-------------|
| `app/config.py` | добавлен флаг `HTTPS_ENABLED` (env, по умолчанию `0`) |
| `app/__init__.py` | при `HTTPS_ENABLED=1`: `ProxyFix(x_proto=1, x_host=1)`, `PREFERRED_URL_SCHEME='https'`, `SESSION_COOKIE_SECURE`, `REMEMBER_COOKIE_SECURE` |
| `deploy/sprinthost/htaccess` | редирект http→https по `X-Forwarded-Proto`, ACME-путь исключён, канонический редирект с Duck DNS-алиаса |
| `.env.example` | документирована переменная `HTTPS_ENABLED` |

Коммит: `49b7d7c` (запушен в `ukichan2285/schedule_sevsu_dz`, ветка `main`).

## 3. Главные грабли: `%{HTTPS}` в Apache всегда `off`

Перед Apache стоит **openresty (nginx)**, TLS терминируется на нём, а в Apache приходит обычный
HTTP на порт 80:

```
HTTPS=None
SERVER_PORT='80'
HTTP_X_FORWARDED_PROTO='https'   # ← реальная схема только здесь
```

Поэтому «классическое» правило

```apache
RewriteCond %{HTTPS} !=on
RewriteRule ^(.*)$ https://%{HTTP_HOST}/$1 [R=301,L]
```

даёт **бесконечный редирект** (`https://` → 301 на себя). Рабочее условие:

```apache
RewriteCond %{HTTP:X-Forwarded-Proto} !https [NC]
```

Это же объясняет, почему `ProxyFix` в приложении обязателен: без него Flask считает запрос
незащищённым, и `url_for(..., _external=True)` / редиректы дают `http://`.

## 4. Что осталось на хосте

```
~/schedule_app/.env                          HTTPS_ENABLED=1, SECRET_KEY перевыпущен
~/schedule_app/.backup/2026-10-26-0907/      бэкап config.py, __init__.py, .env, .htaccess
~/domains/schedule-sevsu.ru/public_html/     site.wsgi + .htaccess (боевые)
```

Перезапуск сайта после правок: `touch ~/domains/schedule-sevsu.ru/public_html/site.wsgi`.
Cron (не менялся, acme-задача удалена):

```cron
*/30 * * * * cd ~/schedule_app && ~/python/bin/python update_once.py >> ~/schedule_app/update.log 2>&1
* * * * * ~/schedule_app/bot_keepalive.sh
```

## 5. Duck DNS — история и отказ

Первоначально домен выдавался через Duck DNS (`schedule-sevsu.duckdns.org`, A → 141.8.192.31,
алиас в панели SprintHost). Схема работает только по HTTP: панель ставит **Let's Encrypt Wildcard**,
который требует DNS-01, т.е. NS хостинга; у `duckdns.org` NS чужие, а по официальной документации
сертификат на **алиас ставится только через поддержку**.

Сертификат для Duck DNS был выпущен вручную (`acme.sh`, webroot, ECC, до 23.01.2027) и лежал
в `~/ssl/`, но установку в Apache пришлось бы каждый раз проводить тикетом. После перехода на
собственный домен всё это удалено: `~/.acme.sh`, `~/ssl`, cron-задача acme.sh, строка в `~/.bashrc`
(бэкап — `~/.bashrc.bak-acme`). Алиас в панели больше не обслуживается (404 от openresty),
запись в Duck DNS можно удалить.

## 6. Откат

1. `cp -a ~/schedule_app/.backup/2026-10-26-0907/{config.py,__init__.py} ~/schedule_app/app/`
2. `cp -a ~/schedule_app/.backup/2026-10-26-0907/.htaccess ~/domains/schedule-sevsu.ru/public_html/`
3. В `~/schedule_app/.env` поставить `HTTPS_ENABLED=0` (или вернуть `.env` из бэкапа)
4. `touch ~/domains/schedule-sevsu.ru/public_html/site.wsgi`

Сертификат при этом остаётся установленным — сайт просто перестанет форсировать https.

## 7. Дальше по PLAN.md

- [ ] Сменить пароль админа на боевой.
- [ ] `TELEGRAM_ADMIN_ID` — сейчас id бота (`8887484529`), нужен id человека (бот показывает в `/start`).
- [ ] Уведомления об изменениях расписания, «последнее обновление» на сайте, экспорт `.ics`, бэкап БД.
