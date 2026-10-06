#!/bin/bash
# Автоперезапуск Telegram-бота (держать на хосте рядом с БД).
# Запускается из cron каждую минуту: если процесса нет — поднимаем.
cd /home/broarik843/schedule_app || exit 1
if ! pgrep -f '[s]tart_bot.py' >/dev/null 2>&1; then
    setsid nohup /home/broarik843/python/bin/python start_bot.py >> bot.log 2>&1 &
    echo "$(date '+%F %T') bot restarted by keepalive" >> bot.log
fi
