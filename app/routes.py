from flask import Blueprint, render_template, request, redirect, flash, jsonify, send_file, abort
from datetime import datetime, timedelta
from io import BytesIO

from sqlalchemy.orm import joinedload

from app.models import (Schedule, Homework, HomeworkFile, ScheduleChange,
                        Exam, Deadline, SessionInfo, SessionFile, Session)
from app.updater import run_update
from app.ics_parser import DAY_NAMES, day_name_for, week_monday

main = Blueprint('main', __name__)


@main.app_template_filter('human_size')
def _human_size(size):
    """Читаемый размер файла: 1.5 МБ, 230 КБ, 0 Б."""
    if size is None:
        return '0 Б'
    size = int(size)
    if size >= 1024 * 1024:
        return f'{size / (1024 * 1024):.1f} МБ'
    if size >= 1024:
        return f'{size / 1024:.0f} КБ'
    return f'{size} Б'


def current_monday():
    return week_monday()


def get_week_lessons(monday):
    """Занятия за конкретную учебную неделю (по понедельнику)."""
    session = Session()
    try:
        lessons = (session.query(Schedule)
                   .options(joinedload(Schedule.homework).joinedload(Homework.files))
                   .filter(Schedule.period_start == monday)
                   .order_by(Schedule.lesson_number)
                   .all())
        return {d: [l for l in lessons if l.day_of_week == d] for d in DAY_NAMES}
    finally:
        session.close()


def get_day_lessons(day_name, monday):
    session = Session()
    try:
        return (session.query(Schedule)
                .options(joinedload(Schedule.homework).joinedload(Homework.files))
                .filter(Schedule.period_start == monday,
                        Schedule.day_of_week == day_name)
                .order_by(Schedule.lesson_number)
                .all())
    finally:
        session.close()


@main.route('/')
def index():
    """Расписание на сегодня (в рамках текущей учебной недели)."""
    monday = current_monday()
    today_day = day_name_for(datetime.now().date())
    lessons = get_day_lessons(today_day, monday) if today_day else []
    return render_template('index.html', lessons=lessons, today=today_day or 'Воскресенье',
                           monday=monday)


@main.route('/week')
def week():
    """Расписание на неделю с навигацией."""
    offset = request.args.get('offset', 0, type=int)
    monday = current_monday() + timedelta(weeks=offset)
    schedule = get_week_lessons(monday)
    has_lessons = any(schedule.values())
    week_dates = [(day, monday + timedelta(days=i)) for i, day in enumerate(DAY_NAMES)]
    return render_template('week.html', schedule=schedule, days=DAY_NAMES,
                           has_lessons=has_lessons, monday=monday, offset=offset,
                           week_dates=week_dates, today=datetime.now().date())


@main.route('/day/<day_name>')
def day_schedule(day_name):
    offset = request.args.get('offset', 0, type=int)
    monday = current_monday() + timedelta(weeks=offset)
    lessons = get_day_lessons(day_name, monday)
    today_name = day_name_for(datetime.now().date())
    # Живая шкала имеет смысл только для текущей недели и сегодняшнего дня:
    # иначе на странице будущей/прошлой недели показывалось бы «идёт пара»
    # по времени сегодняшнего дня.
    is_today = (offset == 0 and day_name == today_name)
    return render_template('day.html', lessons=lessons, day=day_name,
                           monday=monday, offset=offset, is_today=is_today)


@main.route('/changes')
def changes():
    """Последние изменения расписания."""
    session = Session()
    try:
        items = (session.query(ScheduleChange)
                 .order_by(ScheduleChange.detected_at.desc())
                 .limit(50).all())
        return render_template('changes.html', changes=items)
    finally:
        session.close()


@main.route('/session')
def session_page():
    """Расписание сессии и дедлайны по предметам."""
    session = Session()
    try:
        today = datetime.now().date()
        exams = (session.query(Exam)
                 .order_by(Exam.date, Exam.time_start)
                 .all())
        upcoming_exams = [e for e in exams if e.date >= today]
        past_exams = [e for e in exams if e.date < today]
        deadlines = (session.query(Deadline)
                     .order_by(Deadline.is_done,
                               Deadline.due_date.is_(None),
                               Deadline.due_date,
                               Deadline.due_time)
                     .all())
        info = session.get(SessionInfo, 1)
        return render_template('session.html',
                               upcoming_exams=upcoming_exams,
                               past_exams=past_exams,
                               deadlines=deadlines,
                               today=today,
                               info=info)
    finally:
        session.close()


@main.route('/session/file/<int:file_id>')
def session_file(file_id):
    """Отдать вложение к экзамену/дедлайну (фото/PDF) из БД."""
    session = Session()
    try:
        f = session.get(SessionFile, file_id)
        if not f or not f.data:
            abort(404)
        return send_file(
            BytesIO(f.data),
            mimetype=f.mime_type or 'application/octet-stream',
            download_name=f.file_name or f'file_{f.id}',
            as_attachment=False,
            max_age=3600,
        )
    finally:
        session.close()


@main.route('/homework/file/<int:file_id>')
def homework_file(file_id):
    """Отдать вложение к ДЗ (фото/файл) из БД."""
    session = Session()
    try:
        f = session.get(HomeworkFile, file_id)
        if not f or not f.data:
            abort(404)
        return send_file(
            BytesIO(f.data),
            mimetype=f.mime_type or 'application/octet-stream',
            download_name=f.file_name or f'file_{f.id}',
            as_attachment=False,
            max_age=3600,
        )
    finally:
        session.close()


@main.route('/update_schedule')
def update_schedule():
    """Обновить расписание из календаря."""
    back = request.args.get('next') or '/'
    result = run_update()
    if result.get('ok'):
        flash(f"Расписание обновлено: +{result['added']} / −{result['removed']} "
              f"(всего {result['total']})", 'success')
    else:
        flash(f"Не удалось обновить: {result.get('error')}", 'error')
    return redirect(back)


# ─── JSON API (для бота и фронтенда) ───

def _lesson_json(l):
    hw = l.homework
    return {
        'id': l.id,
        'day_of_week': l.day_of_week,
        'lesson_number': l.lesson_number,
        'time_start': l.time_start,
        'time_end': l.time_end,
        'subject': l.subject,
        'teacher': l.teacher,
        'location': l.location,
        'lesson_type': l.lesson_type,
        'homework': hw.text if hw else None,
        'homework_files': [f.to_dict() for f in hw.files] if hw else [],
    }


@main.route('/api/schedule')
def api_schedule():
    offset = request.args.get('offset', 0, type=int)
    monday = current_monday() + timedelta(weeks=offset)
    schedule = get_week_lessons(monday)
    return jsonify({
        'period_start': monday.isoformat(),
        'days': {day: [_lesson_json(l) for l in lessons]
                 for day, lessons in schedule.items()},
    })


@main.route('/api/changes')
def api_changes():
    session = Session()
    try:
        items = (session.query(ScheduleChange)
                 .order_by(ScheduleChange.detected_at.desc())
                 .limit(20).all())
        return jsonify([
            {'detected_at': c.detected_at.isoformat() if c.detected_at else None,
             'changes': c.changes}
            for c in items
        ])
    finally:
        session.close()
