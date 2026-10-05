"""Автообновление расписания из .ics-календаря SEVSU.

Скачивает календарь, сравнивает с тем, что уже в БД, и записывает изменения
в таблицу schedule_changes.
"""
import logging
from datetime import datetime, timedelta

import requests

from app.models import Session, Schedule, ScheduleChange, init_db
from app.ics_parser import parse_ics, week_monday
from app import config

log = logging.getLogger('updater')

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def fetch_ics(url=None, timeout=25):
    """Скачать .ics без системных прокси/VPN. Возвращает (text, error)."""
    url = url or config.SCHEDULE_ICS_URL
    if not url:
        return None, 'SCHEDULE_ICS_URL не задан (см. .env)'

    s = requests.Session()
    s.trust_env = False
    if config.SCHEDULE_PROXY:
        # Ходим через прокси (например, российский), игнорируя системные
        s.proxies = {'http': config.SCHEDULE_PROXY, 'https': config.SCHEDULE_PROXY}
    else:
        s.proxies = {'http': None, 'https': None}
    s.headers.update({
        'User-Agent': USER_AGENT,
        'Accept-Language': 'ru-RU,ru;q=0.9',
        'Accept': 'text/calendar,text/plain,*/*',
    })
    try:
        r = s.get(url, timeout=timeout)
    except requests.exceptions.RequestException as e:
        return None, f'сеть: {e}'

    if r.status_code == 403:
        return None, 'HTTP 403 (DDoS-Guard) — нужен российский IP (выключите VPN)'
    if r.status_code != 200:
        return None, f'HTTP {r.status_code}'
    if 'BEGIN:VCALENDAR' not in r.text[:300]:
        return None, 'ответ не похож на .ics'
    return r.text, None


def _key(period_start, day, num, subject, teacher, location, ltype):
    try:
        num = int(num) if num is not None else 0
    except (TypeError, ValueError):
        num = 0
    return (period_start, day or '', num, subject or '', teacher or '',
            location or '', ltype or '')


def run_update(url=None, weeks_ahead=None, record_changes=True):
    """Одно обновление расписания. Возвращает словарь с итогом."""
    init_db()
    weeks_ahead = config.WEEKS_AHEAD if weeks_ahead is None else weeks_ahead

    text, err = fetch_ics(url)
    if err:
        log.warning('Календарь не получен: %s', err)
        return {'ok': False, 'error': err}

    lessons = parse_ics(text, all_weeks=True)

    today = datetime.now().date()
    cur_mon = week_monday(today)
    max_mon = cur_mon + timedelta(weeks=weeks_ahead)

    new_map = {}
    for l in lessons:
        p = week_monday(l['date'])
        if p < cur_mon or p > max_mon:
            continue
        k = _key(p, l['day_of_week'], l['lesson_number'], l['subject'],
                 l['teacher'], l['location'], l['lesson_type'])
        new_map[k] = l

    session = Session()
    try:
        # Пометить «старые» записи без периода текущей неделей
        session.query(Schedule).filter(Schedule.period_start.is_(None)).update(
            {Schedule.period_start: cur_mon}, synchronize_session=False)

        existing = (session.query(Schedule)
                    .filter(Schedule.period_start >= cur_mon,
                            Schedule.period_start <= max_mon)
                    .all())
        existing_map = {
            _key(r.period_start, r.day_of_week, r.lesson_number, r.subject,
                 r.teacher, r.location, r.lesson_type): r
            for r in existing
        }

        added = [k for k in new_map if k not in existing_map]
        removed = [k for k in existing_map if k not in new_map]

        for k in added:
            l = new_map[k]
            session.add(Schedule(
                date=l['date'],
                period_start=k[0],
                day_of_week=l['day_of_week'],
                lesson_number=l['lesson_number'],
                subject=l['subject'],
                teacher=l['teacher'],
                location=l['location'],
                lesson_type=l['lesson_type'],
                hash=l['hash'],
                created_at=l['created_at'],
                updated_at=l['updated_at'],
            ))

        for k in removed:
            session.delete(existing_map[k])

        if record_changes and (added or removed):
            lines = []
            for k in sorted(added, key=lambda x: (x[0], x[2])):
                lines.append(f'+ {k[0].strftime("%d.%m")} {k[1]} п.{k[2]}: {k[3]}')
            for k in sorted(removed, key=lambda x: (x[0], x[2])):
                lines.append(f'− {k[0].strftime("%d.%m")} {k[1]} п.{k[2]}: {k[3]}')
            session.add(ScheduleChange(changes='\n'.join(lines),
                                       detected_at=datetime.now()))

        session.commit()
        result = {
            'ok': True,
            'added': len(added),
            'removed': len(removed),
            'total': len(new_map),
            'periods': sorted({k[0] for k in new_map}),
        }
        log.info('Обновление: +%s / -%s (всего %s)', result['added'],
                 result['removed'], result['total'])
        return result
    except Exception as e:  # noqa: BLE001
        session.rollback()
        log.exception('Ошибка записи расписания')
        return {'ok': False, 'error': str(e)}
    finally:
        session.close()


if __name__ == '__main__':
    import json
    print(json.dumps(run_update(), ensure_ascii=False, default=str))
