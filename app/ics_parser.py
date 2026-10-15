"""Разбор .ics-календаря SEVSU и вспомогательные функции."""
import re
import hashlib
from datetime import datetime, timedelta

# Расписание звонков (пара -> начало, конец)
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

# Учебные дни (без воскресенья). Единый источник для сайта, бота и админки.
DAY_NAMES = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']
DAY_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']

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


def unfold_ics(text):
    """RFC 5545: строки, начинающиеся с пробела/таба — продолжение предыдущей."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    out = []
    for line in text.split('\n'):
        if line[:1] in (' ', '\t') and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _unescape(value):
    return (value.replace('\\n', '\n').replace('\\N', '\n')
                 .replace('\\,', ',').replace('\\;', ';').replace('\\\\', '\\'))


def parse_dt(value):
    """'20260901T083000' -> (datetime, time)"""
    m = re.match(r'(\d{8})(?:T(\d{6}))?', value.strip())
    if not m:
        return None, None
    d = datetime.strptime(m.group(1), '%Y%m%d')
    t = datetime.strptime(m.group(2), '%H%M%S').time() if m.group(2) else None
    return d, t


def pair_by_time(t):
    """Определить номер пары по времени начала."""
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


def split_summary(summary):
    """
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


def extract_teacher(description):
    """
    'Преподаватель: Иванов Иван'            -> 'Иванов Иван'
    '1-я подгруппа\\nПреподаватель: Петров'  -> 'Петров'
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


def make_lesson(day_of_week, lesson_number, subject, teacher, location, lesson_type,
                date=None, subgroup=None, time_start=None, time_end=None):
    now = datetime.now()
    if subgroup:
        lesson_type = f'{lesson_type} (подгр. {subgroup})'.strip()
    hash_str = f'{day_of_week}|{lesson_number}|{subject}|{teacher}|{location}|{lesson_type}|{time_start}|{time_end}'
    return {
        'day_of_week': day_of_week or '',
        'lesson_number': lesson_number,
        'subject': subject or '',
        'teacher': teacher or '',
        'location': location or '',
        'lesson_type': lesson_type or '',
        'time_start': time_start,
        'time_end': time_end,
        'hash': hashlib.md5(hash_str.encode()).hexdigest(),
        'created_at': now,
        'updated_at': now,
        'date': date or now,
    }


def week_monday(d=None):
    """Понедельник недели для даты/датетайма (по умолчанию — сегодня)."""
    if d is None:
        d = datetime.now().date()
    if isinstance(d, datetime):
        d = d.date()
    return d - timedelta(days=d.weekday())


def day_name_for(d):
    """Название учебного дня для даты; воскресенье -> None."""
    i = d.weekday()
    return DAY_NAMES[i] if i < len(DAY_NAMES) else None


def fmt_week(monday):
    """'07.10–12.10.2026' для подписей недели."""
    end = monday + timedelta(days=5)
    return f"{monday.strftime('%d.%m')}–{end.strftime('%d.%m.%Y')}"


def dedupe(lessons, key_func=None):
    seen = set()
    out = []
    for l in lessons:
        if key_func:
            key = key_func(l)
        else:
            key = (l['day_of_week'], l['lesson_number'], l['subject'],
                   l['teacher'], l['location'], l['lesson_type'])
        if key in seen:
            continue
        seen.add(key)
        out.append(l)
    return out


def parse_ics(text, week_offset=0, all_weeks=False, dedupe_weeks=False):
    """
    Разобрать .ics в список занятий.

    week_offset — 0=текущая неделя, 1=следующая, -1=прошлая (если all_weeks=False)
    all_weeks   — разобрать весь календарь
    dedupe_weeks— если all_weeks=True, схлопнуть повторяющиеся недели
    """
    events = []
    cur = None
    for line in unfold_ics(text):
        if line == 'BEGIN:VEVENT':
            cur = {}
        elif line == 'END:VEVENT':
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ':' in line:
            name, _, value = line.partition(':')
            name = name.split(';')[0].upper()
            value = _unescape(value)
            if name in cur:
                cur[name] = cur[name] + '\n' + value
            else:
                cur[name] = value

    today = datetime.now()
    week_start = (today - timedelta(days=today.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0) + timedelta(days=7 * week_offset)
    week_end = week_start + timedelta(days=7)

    lessons = []
    for ev in events:
        d, t = parse_dt(ev.get('DTSTART', ''))
        if not d:
            continue
        if not all_weeks and not (week_start <= d < week_end):
            continue

        day_of_week = DAY_NAMES[d.weekday()]
        lesson_number = pair_by_time(t)
        # Реальное время пары берём из календаря (DTSTART/DTEND), а не из BELLS
        _, end_t = parse_dt(ev.get('DTEND', ''))
        time_start = t.strftime('%H:%M') if t else None
        time_end = end_t.strftime('%H:%M') if end_t else None
        subgroup, lesson_type, subject = split_summary(ev.get('SUMMARY', ''))
        teacher = extract_teacher(ev.get('DESCRIPTION', ''))
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
            time_start=time_start,
            time_end=time_end,
        ))

    if all_weeks and dedupe_weeks:
        lessons = dedupe(lessons)
    return lessons
