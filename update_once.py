#!/usr/bin/env python3
"""Однократное обновление расписания — для cron на хостинге.

Пример для Render Cron Job / crontab:
    */30 * * * * cd /app && python update_once.py
"""
import json

from app.updater import run_update

if __name__ == '__main__':
    res = run_update()
    print(json.dumps(res, ensure_ascii=False, default=str))
    raise SystemExit(0 if res.get('ok') else 1)
