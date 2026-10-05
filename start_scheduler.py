#!/usr/bin/env python3
"""Фоновый планировщик автообновления расписания.

Запуск:
    python start_scheduler.py
"""
import logging
import time

import schedule

from app import config
from app.updater import run_update

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
)


def job():
    res = run_update()
    if res.get('ok'):
        print(f"✅ +{res['added']} / −{res['removed']} (всего {res['total']})")
    else:
        print(f"⚠️ Не обновлено: {res.get('error')}")


def main():
    interval = config.UPDATE_INTERVAL_MINUTES
    print(f'⏰ Планировщик запущен. Интервал: {interval} мин. URL: {config.SCHEDULE_ICS_URL or "НЕ ЗАДАН"}')
    job()  # обновляем сразу при старте
    schedule.every(interval).minutes.do(job)
    while True:
        schedule.run_pending()
        time.sleep(20)


if __name__ == '__main__':
    main()
