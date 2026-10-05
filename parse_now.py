#!/usr/bin/env python3
"""
Парсер расписания SEVSU.

Сайт schedule.sevsu.ru — SPA: расписание грузится JavaScript'ом, в HTML его нет.
Поэтому поддерживаются форматы, которые можно получить из браузера (без VPN):

    1) .ics  — календарь, кнопка «Получить ссылку на календарь» в настройках сайта
    2) .json — ответ API из DevTools → Network
    3) .html — сохранённый DOM (Elements → Copy outerHTML) после отрисовки

Использование:
    python parse_now.py --ip                              # проверить внешний IP
    python parse_now.py --input data/schedule.ics         # текущая неделя
    python parse_now.py --input data/schedule.ics --week-offset 1   # след. неделя
    python parse_now.py --input data/schedule.ics --all-weeks       # весь семестр
    python parse_now.py --input data/api.json
    python parse_now.py --input data/rendered.html

    # сбросить расписание в БД и залить заново:
    python parse_now.py --input data/schedule.ics --reset
"""

import sys
import os
import re
import json
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
import hashlib
from app.parser import ScheduleParser
from app.models import Session, Schedule, Homework, ScheduleChange, init_db

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, 'data')

DEFAULT_GROUP = 'rs-s-26-1-o'

# Расписание звонков с сайта (пара -> начало, конец)
BELLS = [
    (1, '08:30', '10:00'),
    (2, '10:10', '11:40'),
    (3, '11:50', '13:20'),
    (4, '14:00', '15:30'),
    (5, '15:40', '17:10'),
    (6, '17:20', '18:50'),
    (7, '19:00', '20:30'),
    (8, '20:40', '22:10'),
]

DAY_NAMES = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']

# Коды типов занятий из календаря SEVSU
TYPE_MAP = {
    'пз': 'практика',
    'лз': 'лабораторная',
    'лекция': 'лекция',
    'лек': 'лекция',
    'сем': 'семинар',
    'сем.': 'семинар',
    'вуд': 'ВУД',
}


# ────────────────────────── HTTP ──────────────────────────

def check_ip():
    no_proxy = {'http': None, 'https': None}
    try:
        r = requests.get('https://api.ipify.org?format=json', timeout=5, proxies=no_proxy)
        ip = r.json()['ip']
        print(f'🌐 Ваш внешний IP: {ip}')
        return ip
    except Exception as e:
        print(f'⚠️ Не удалось определить IP: {e}')
        return None


def fetch_schedule_page(group_name, parser):
    url = f'https://schedule.sevsu.ru/groups/{group_name}'
    print(f'\n📥 Загрузка: {url}')

    html = None
    for attempt in range(1, 4):
        try:
            print(f'   Попытка {attempt}/3...')
            response = parser.session.get(url, timeout=20)
            print(f'   HTTP {response.status_code}')

            if response.status_code == 403:
                print('   ⚠️ 403 Forbidden (DDoS-Guard)')
                time.sleep(3)
                html = None
                continue

            response.raise_for_status()
            html = response.text
            print(f'   ✅ HTML получен ({len(html)} байт)')
            break
        except requests.exceptions.RequestException as e:
            print(f'   ❌ Ошибка: {e}')
            time.sleep(2)

    return html


def fetch_ics_from_url(url):
    """Скачать .ics напрямую по ссылке (без VPN/прокси)"""
    print(f'\n📥 Скачивание календаря: {url}')
    s = requests.Session()
    s.trust_env = False
    s.proxies = {'http': None, 'https': None}
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'ru-RU,ru;q=0.9',
    })
    try:
        r = s.get(url, timeout=20)
        print(f'   HTTP {r.status_code}, {len(r.text)} байт')
        if r.status_code != 200:
            if r.status_code == 403:
                print('   ⚠️ 403 (DDoS-Guard). Нужен российский IP — выключите VPN.')
            return None
        if 'BEGIN:VCALENDAR' not in r.text[:200]:
            print('   ⚠️ Ответ не похож на .ics (возможно, страница-защита)')
            return None
        out_path = os.path.join(DATA_DIR, 'schedule.ics')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(r.text)
        print(f'   ✅ Сохранено: {out_path}')
        return r.text
    except requests.exceptions.RequestException as e:
        print(f'   ❌ Ошибка запроса: {e}')
        return None


def detect_ddos_guard(html):
    if not html:
        return True
    markers = ['ddos-guard', 'DDoS-Guard', '__ddg8_', '__ddg9_', '__ddg10_', 'cdn-cgi']
    return any(m in html for m in markers)


# ────────────────────────── ICS ──────────────────────────

def _unfold_ics(text):
    """RFC 5545: строки, начинающиеся с пробела/таба — продолжение предыдущей."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    out = []
    for line in text.split('\n'):
        if line[:1] in (' ', '\t') and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _ics_unescape(value):
    return (value.replace('\\n', '\n').replace('\\N', '\n')
                 .replace('\\,', ',').replace('\\;', ';').replace('\\\\', '\\'))


def _parse_ics_dt(value):
    """'20260901T083000' -> (datetime, time)"""
    m = re.match(r'(\d{8})(?:T(\d{6}))?', value.strip())
    if not m:
        return None, None
    d = datetime.strptime(m.group(1), '%Y%m%d')
    t = datetime.strptime(m.group(2), '%H%M%S').time() if m.group(2) else None
    return d, t


def _pair_by_time(t):
    """Определить номер пары по времени начала"""
    if not t:
        return None
    hhmm = t.strftime('%H:%M')
    for num, start, end in BELLS:
        if start == hhmm:
            return num
    best = None
    for num, start, end in BELLS:
        if start <= hhmm:
            best = num
    return best


def _split_summary(summary):
    """
    Разобрать SUMMARY календаря SEVSU.
    '[1] ЛЗ: Цифровое проектирование' -> (1, 'лабораторная', 'Цифровое проектирование')
    'Лекция: Физика'                 -> (None, 'лекция', 'Физика')
    'ПЗ: Высшая математика:Раздел'   -> (None, 'практика', 'Высшая математика:Раздел')
    """
    s = (summary or '').strip()
    subgroup = None
    m = re.match(r'^\[(\d+)\]\s*', s)
    if m:
        subgroup = int(m.group(1))
        s = s[m.end():]

    lesson_type = ''
    subject = s
    if ':' in s:
        head, _, tail = s.partition(':')
        code = head.strip().lower()
        if code in TYPE_MAP:
            lesson_type = TYPE_MAP[code]
            subject = tail.strip()
    return subgroup, lesson_type, subject


def _extract_teacher(description):
    """
    DESCRIPTION:
        'Преподаватель: Иванов Иван Иванович'
        '1-я подгруппа\\nПреподаватель: Петров Пётр Петрович'
    -> 'Иванов Иван Иванович'
    """
    d = (description or '').strip()
    if not d:
        return ''
    parts = [p.strip() for p in d.split('\n') if p.strip()]
    for p in parts:
        m = re.match(r'^Преподавател[ья][:\s]*(.+)$', p, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    nonsub = [p for p in parts if not re.match(r'^\d+-я\s+подгруппа', p, re.IGNORECASE)]
    return nonsub[0] if nonsub else ''


def parse_ics(text, group_name=DEFAULT_GROUP, week_offset=0, all_weeks=False):
    events = []
    cur = None
    for line in _unfold_ics(text):
        if line == 'BEGIN:VEVENT':
            cur = {}
        elif line == 'END:VEVENT':
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ':' in line:
            name, _, value = line.partition(':')
            name = name.split(';')[0].upper()
            value = _ics_unescape(value)
            if name in cur:
                cur[name] = cur[name] + '\n' + value
            else:
                cur[name] = value

    # Границы недели
    today = datetime.now()
    week_start = (today - timedelta(days=today.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0) + timedelta(days=7 * week_offset)
    week_end = week_start + timedelta(days=7)
    if not all_weeks:
        print(f'📅 Период: {week_start.date()} — {(week_end - timedelta(days=1)).date()} '
              f'(неделя, смещение {week_offset})')

    lessons = []
    for ev in events:
        d, t = _parse_ics_dt(ev.get('DTSTART', ''))
        if not d:
            continue
        if not all_weeks and not (week_start <= d < week_end):
            continue

        day_of_week = DAY_NAMES[d.weekday()]
        lesson_number = _pair_by_time(t)
        subgroup, lesson_type, subject = _split_summary(ev.get('SUMMARY', ''))
        teacher = _extract_teacher(ev.get('DESCRIPTION', ''))
        location = (ev.get('LOCATION', '') or '').strip()

        lessons.append(make_lesson(
            day_of_week=day_of_week,
            lesson_number=lesson_number,
            subject=subject,
            teacher=teacher,
            location=location,
            lesson_type=lesson_type,
            date=d,
            subgroup=subgroup,
        ))

    return lessons


# ────────────────────────── JSON ──────────────────────────

def parse_json_data(data, group_name=DEFAULT_GROUP):
    print('\n🔎 Структура JSON (для отладки):')

    def describe(obj, prefix='', depth=0):
        if depth > 2:
            return
        if isinstance(obj, dict):
            for k, v in list(obj.items())[:20]:
                t = type(v).__name__
                extra = ''
                if isinstance(v, (str, int, float)):
                    extra = f' = {str(v)[:60]}'
                elif isinstance(v, list):
                    extra = f' [{len(v)} элементов]'
                print(f'   {prefix}{k}: {t}{extra}')
                if isinstance(v, (dict, list)):
                    describe(v, prefix + '  ', depth + 1)
        elif isinstance(obj, list) and obj:
            describe(obj[0], prefix + '  ', depth + 1)

    describe(data)

    candidates = []

    def walk(o):
        if isinstance(o, list) and o and isinstance(o[0], dict):
            keys = set(o[0].keys())
            if keys & {'subject', 'name', 'discipline', 'lesson', 'title', 'predmet'}:
                candidates.append(o)
        if isinstance(o, dict):
            for v in o.values():
                walk(v)

    walk(data)

    if not candidates:
        print('\n⚠️ Не удалось автоматически найти список занятий в JSON.')
        print('   Пришлите этот JSON — подстроим парсер.')
        return []

    items = max(candidates, key=len)
    print(f'\n✅ Кандидат: список из {len(items)} объектов')

    lessons = []
    for it in items:
        subject = (it.get('subject') or it.get('name') or it.get('discipline')
                   or it.get('lesson') or it.get('title') or '')
        teacher = (it.get('teacher') or it.get('prepod') or it.get('lector') or '')
        location = (it.get('location') or it.get('auditory') or it.get('room')
                    or it.get('aud') or it.get('cabinet') or '')
        lesson_type = (it.get('type') or it.get('lesson_type') or '')
        day = (it.get('day') or it.get('day_of_week') or it.get('weekday') or '')
        number = it.get('number') or it.get('pair') or it.get('lesson_number')
        try:
            number = int(number) if number is not None else None
        except Exception:
            number = None
        subgroup = it.get('subgroup') or it.get('sub')
        if not subject and not teacher:
            continue
        lessons.append(make_lesson(day, number, subject, teacher, location, lesson_type, subgroup=subgroup))
    return lessons


# ────────────────────────── Общее ──────────────────────────

def make_lesson(day_of_week, lesson_number, subject, teacher, location, lesson_type,
                date=None, subgroup=None):
    now = datetime.now()
    if subgroup:
        lesson_type = f'{lesson_type} (подгр. {subgroup})'.strip()
    hash_str = f'{day_of_week}|{lesson_number}|{subject}|{teacher}|{location}|{lesson_type}'
    return {
        'day_of_week': day_of_week or '',
        'lesson_number': lesson_number,
        'subject': subject or '',
        'teacher': teacher or '',
        'location': location or '',
        'lesson_type': lesson_type or '',
        'hash': hashlib.md5(hash_str.encode()).hexdigest(),
        'created_at': now,
        'updated_at': now,
        'date': date or now,
    }


def dedupe(lessons):
    seen = set()
    out = []
    for l in lessons:
        key = (l['day_of_week'], l['lesson_number'], l['subject'], l['teacher'], l['location'])
        if key in seen:
            continue
        seen.add(key)
        out.append(l)
    return out


def read_input(path):
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()


def save_lessons_to_json(lessons, out_name):
    if not lessons:
        return None
    os.makedirs(DATA_DIR, exist_ok=True)
    json_lessons = []
    for l in lessons:
        item = dict(l)
        item['created_at'] = item['created_at'].isoformat()
        item['updated_at'] = item['updated_at'].isoformat()
        item.pop('date', None)
        json_lessons.append(item)
    path = os.path.join(DATA_DIR, out_name)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(json_lessons, f, ensure_ascii=False, indent=2)
    print(f'💾 JSON сохранён: {path}')
    return path


def save_lessons_to_db(lessons, reset=False):
    init_db()
    session = Session()
    saved = 0
    skipped = 0
    try:
        if reset:
            session.query(Homework).delete()
            session.query(ScheduleChange).delete()
            deleted = session.query(Schedule).delete()
            print(f'🧹 Сброс: удалено записей расписания: {deleted}')
            session.commit()

        for lesson_data in lessons:
            existing = session.query(Schedule).filter(
                Schedule.day_of_week == lesson_data['day_of_week'],
                Schedule.lesson_number == lesson_data['lesson_number'],
                Schedule.subject == lesson_data['subject'],
                Schedule.teacher == lesson_data['teacher'],
                Schedule.location == lesson_data['location'],
            ).first()
            if existing:
                skipped += 1
                continue
            session.add(Schedule(
                date=lesson_data['created_at'],
                day_of_week=lesson_data['day_of_week'],
                lesson_number=lesson_data['lesson_number'],
                subject=lesson_data['subject'],
                teacher=lesson_data['teacher'],
                location=lesson_data['location'],
                lesson_type=lesson_data['lesson_type'],
                hash=lesson_data['hash'],
                created_at=lesson_data['created_at'],
                updated_at=lesson_data['updated_at'],
            ))
            saved += 1
        session.commit()
        print(f'✅ В БД новых: {saved}, пропущено (уже есть): {skipped}')
        return True
    except Exception as e:
        session.rollback()
        print(f'❌ Ошибка записи в БД: {e}')
        return False
    finally:
        session.close()


def show_examples(lessons, limit=12):
    print('\n' + '═' * 70)
    print('   Занятия:')
    print('═' * 70)
    for lesson in lessons[:limit]:
        line = f'  {lesson["day_of_week"]:<12} п.{lesson["lesson_number"]} '
        line += f'│ {lesson["subject"]}'
        if lesson["lesson_type"]:
            line += f' [{lesson["lesson_type"]}]'
        if lesson["teacher"]:
            line += f' │ {lesson["teacher"]}'
        if lesson["location"]:
            line += f' │ {lesson["location"]}'
        print(line)
    print('═' * 70)


def main():
    import argparse
    ap = argparse.ArgumentParser(description='Парсер расписания SEVSU')
    ap.add_argument('--group', default=DEFAULT_GROUP)
    ap.add_argument('--input', help='Файл: .ics / .json / .html')
    ap.add_argument('--url', help='Скачать .ics напрямую по ссылке календаря')
    ap.add_argument('--from-file', action='store_true', help='Разобрать data/group_<group>.html')
    ap.add_argument('--week-offset', type=int, default=0, help='0=текущая неделя, 1=следующая, -1=прошлая')
    ap.add_argument('--all-weeks', action='store_true', help='Не фильтровать по неделе')
    ap.add_argument('--reset', action='store_true', help='Очистить расписание в БД перед импортом')
    ap.add_argument('--ip', action='store_true')
    args = ap.parse_args()

    if args.ip:
        check_ip()
        return 0

    print('═' * 70)
    print('   Парсер расписания SEVSU')
    print('═' * 70)
    print(f'   Группа: {args.group}')
    print('═' * 70)

    lessons = []

    input_path = args.input
    if args.from_file:
        input_path = os.path.join(DATA_DIR, f'group_{args.group}.html')

    # 1) Прямое скачивание .ics по ссылке календаря
    if args.url:
        text = fetch_ics_from_url(args.url)
        if not text:
            return 1
        lessons = parse_ics(text, args.group, args.week_offset, args.all_weeks)
    elif input_path:
        if not os.path.exists(input_path):
            print(f'❌ Файл не найден: {input_path}')
            return 1
        text = read_input(input_path)
        ext = os.path.splitext(input_path)[1].lower()
        print(f'\n📂 Разбор файла: {input_path} ({len(text)} байт)')

        if ext == '.ics':
            lessons = parse_ics(text, args.group, args.week_offset, args.all_weeks)
        elif ext == '.json':
            try:
                lessons = parse_json_data(json.loads(text), args.group)
            except json.JSONDecodeError as e:
                print(f'❌ Некорректный JSON: {e}')
                return 1
        else:
            parser = ScheduleParser()
            lessons = parser.parse_schedule(text)
            if not lessons:
                print('⚠️ В HTML занятий не найдено.')
                print('   Сохраните DOM: F12 → Elements → <html> → Copy → Copy outerHTML')
                return 1
    else:
        check_ip()
        parser = ScheduleParser()
        html = fetch_schedule_page(args.group, parser)
        if not html:
            print('\n❌ Не удалось загрузить страницу.')
            print('   Сайт — SPA, требует JS (DDoS-Guard). Используйте --input с .ics/.json/.html.')
            return 1
        with open(os.path.join(DATA_DIR, f'group_{args.group}.html'), 'w', encoding='utf-8') as f:
            f.write(html)
        if detect_ddos_guard(html):
            print('\n⚠️ Получен DDoS-Guard челлендж.')
            return 1
        lessons = parser.parse_schedule(html)

    lessons = [l for l in lessons if l.get('subject') or l.get('teacher')]
    lessons = dedupe(lessons)
    print(f'\n🔍 Найдено занятий (после дедупликации): {len(lessons)}')

    if not lessons:
        print('\n⚠️ Занятий не найдено. Пришлите входной файл — подстроим парсер.')
        return 1

    save_lessons_to_json(lessons, f'lessons_{args.group}.json')
    save_lessons_to_db(lessons, reset=args.reset)
    show_examples(lessons)
    print('\n🎉 Готово! Проверьте сайт: http://127.0.0.1:5000')
    return 0


if __name__ == '__main__':
    sys.exit(main())
