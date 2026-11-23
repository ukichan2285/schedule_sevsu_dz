"""Админ-панель: авторизация, пользователи, домашние задания, журнал, сессия."""
from functools import wraps
from datetime import datetime, timedelta
import secrets

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session)
from sqlalchemy import func

from app.models import (Session, User, Schedule, Homework, ScheduleChange,
                        Feedback, Exam, Deadline, SessionInfo)
from app.ics_parser import DAY_NAMES, week_monday


# Виды мероприятий в сессии. Порядок важен для выпадающего списка.
EXAM_KINDS = ('экзамен', 'зачёт', 'диф. зачёт', 'консультация')


def _csrf_token():
    """Простой CSRF-токен на основе сессии (без дополнительных зависимостей)."""
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']


def _validate_csrf():
    """Проверить CSRF-токен в POST-запросе."""
    token = request.form.get('csrf_token')
    if not token or token != session.get('csrf_token'):
        flash('Ошибка безопасности: недействительный CSRF-токен', 'error')
        return False
    return True


def _parse_date(value, field_name):
    """Парсит YYYY-MM-DD в date; при ошибке возвращает None и показывает flash."""
    value = (value or '').strip()
    if not value:
        flash(f'Укажите {field_name}', 'error')
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        flash(f'Неверный формат даты для «{field_name}»', 'error')
        return None


def _parse_time(value):
    """Парсит HH:MM в time; пустое значение → None."""
    value = (value or '').strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, '%H:%M').time()
    except ValueError:
        return None


admin = Blueprint('admin', __name__)


# ─────────── Авторизация ───────────

def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    s = Session()
    try:
        return s.get(User, uid)
    finally:
        s.close()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash('Войдите, чтобы продолжить', 'error')
            return redirect(url_for('admin.login', next=request.path))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u:
            flash('Войдите, чтобы продолжить', 'error')
            return redirect(url_for('admin.login', next=request.path))
        if not u.is_admin:
            flash('Нужны права администратора', 'error')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return wrapper


@admin.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        s = Session()
        try:
            u = s.query(User).filter(User.username == username).first()
            if u and u.is_active and u.check_password(password):
                session['user_id'] = u.id
                flash(f'Добро пожаловать, {u.display_name}!', 'success')
                return redirect(request.args.get('next') or url_for('admin.dashboard'))
            flash('Неверное имя или пароль', 'error')
        finally:
            s.close()
    return render_template('login.html')


@admin.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли', 'success')
    return redirect(url_for('main.index'))


# ─────────── Дашборд ───────────

@admin.route('/admin')
@admin_required
def dashboard():
    s = Session()
    try:
        stats = {
            'users': s.query(User).count(),
            'lessons': s.query(Schedule).count(),
            'homework': s.query(Homework).count(),
            'changes': s.query(ScheduleChange).count(),
            'feedback': s.query(Feedback).count(),
            'feedback_unread': s.query(Feedback).filter(Feedback.is_read.is_(False)).count(),
            'exams': s.query(Exam).count(),
            'deadlines': s.query(Deadline).count(),
            'deadlines_done': s.query(Deadline).filter(Deadline.is_done.is_(True)).count(),
        }
    finally:
        s.close()
    return render_template('admin/dashboard.html', stats=stats)


# ─────────── Пользователи ───────────

@admin.route('/admin/users')
@admin_required
def users():
    s = Session()
    try:
        items = s.query(User).order_by(User.id).all()
        users_data = [{
            'id': u.id,
            'username': u.username,
            'display_name': u.display_name,
            'role': u.role,
            'is_active': u.is_active,
            'telegram_id': u.telegram_id,
            'has_password': bool(u.password_hash),
        } for u in items]
    finally:
        s.close()
    return render_template('admin/users.html', users=users_data)


@admin.route('/admin/users/create', methods=['POST'])
@admin_required
def users_create():
    username = (request.form.get('username') or '').strip()
    password = request.form.get('password') or ''
    role = request.form.get('role') or 'user'
    first_name = (request.form.get('first_name') or '').strip()
    last_name = (request.form.get('last_name') or '').strip()

    if not username or not password:
        flash('Укажите имя пользователя и пароль', 'error')
        return redirect(url_for('admin.users'))

    s = Session()
    try:
        if s.query(User).filter(User.username == username).first():
            flash(f'Пользователь «{username}» уже существует', 'error')
            return redirect(url_for('admin.users'))

        min_tid = s.query(func.min(User.telegram_id)).scalar() or 0
        new_tid = min(min_tid, 0) - 1  # временный id для веб-аккаунта

        u = User(
            telegram_id=new_tid,
            username=username,
            first_name=first_name or None,
            last_name=last_name or None,
            role=role if role in ('admin', 'user') else 'user',
            is_active=True,
            created_at=datetime.now(),
        )
        u.set_password(password)
        s.add(u)
        s.commit()
        flash(f'Пользователь «{username}» создан', 'success')
    finally:
        s.close()
    return redirect(url_for('admin.users'))


@admin.route('/admin/homework-users/create', methods=['POST'])
@admin_required
def homework_user_create():
    """Заполняющий ДЗ: вход только через Telegram, пароль не нужен.

    Регистрируется по Telegram ID (обязательно) и, по желанию, username.
    Бот пускает такого пользователя по telegram_id при первом же обращении.
    """
    raw_tid = (request.form.get('telegram_id') or '').strip()
    username = (request.form.get('username') or '').strip() or None
    first_name = (request.form.get('first_name') or '').strip() or None
    last_name = (request.form.get('last_name') or '').strip() or None

    if not raw_tid.isdigit():
        flash('Telegram ID должен быть числом', 'error')
        return redirect(url_for('admin.users'))
    tid = int(raw_tid)

    s = Session()
    try:
        if s.query(User).filter(User.telegram_id == tid).first():
            flash(f'Пользователь с Telegram ID {tid} уже есть', 'error')
            return redirect(url_for('admin.users'))
        if username and s.query(User).filter(User.username == username).first():
            flash(f'Имя «{username}» уже занято', 'error')
            return redirect(url_for('admin.users'))

        s.add(User(
            telegram_id=tid,
            username=username,
            first_name=first_name,
            last_name=last_name,
            role='homework',
            is_active=True,
            created_at=datetime.now(),
        ))
        s.commit()
        flash(f'Заполняющий ДЗ добавлен (Telegram ID {tid})', 'success')
    finally:
        s.close()
    return redirect(url_for('admin.users'))


@admin.route('/admin/users/<int:uid>/edit', methods=['POST'])
@admin_required
def users_edit(uid):
    s = Session()
    try:
        u = s.get(User, uid)
        if not u:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('admin.users'))

        new_username = (request.form.get('username') or '').strip()
        if new_username:
            u.username = new_username
        u.first_name = (request.form.get('first_name') or '').strip() or None
        u.last_name = (request.form.get('last_name') or '').strip() or None
        role = request.form.get('role')
        if role in ('admin', 'user', 'homework'):
            u.role = role
        u.is_active = request.form.get('is_active') == 'on'

        new_password = request.form.get('password') or ''
        if new_password:
            u.set_password(new_password)

        s.commit()
        flash(f'Пользователь «{u.username}» обновлён', 'success')
    finally:
        s.close()
    return redirect(url_for('admin.users'))


@admin.route('/admin/users/<int:uid>/delete', methods=['POST'])
@admin_required
def users_delete(uid):
    me = current_user()
    if me and me.id == uid:
        flash('Нельзя удалить самого себя', 'error')
        return redirect(url_for('admin.users'))
    s = Session()
    try:
        u = s.get(User, uid)
        if u:
            if u.role == 'admin':
                admins = s.query(User).filter(User.role == 'admin').count()
                if admins <= 1:
                    flash('Нельзя удалить последнего администратора', 'error')
                    return redirect(url_for('admin.users'))
            s.query(Homework).filter(Homework.user_id == uid).update(
                {Homework.user_id: 1}, synchronize_session=False)
            s.delete(u)
            s.commit()
            flash('Пользователь удалён', 'success')
    finally:
        s.close()
    return redirect(url_for('admin.users'))


# ─────────── Домашние задания ───────────

@admin.route('/admin/homework')
@login_required
def homework():
    offset = request.args.get('offset', 0, type=int)
    monday = week_monday() + timedelta(weeks=offset)

    s = Session()
    try:
        lessons = (s.query(Schedule)
                   .filter(Schedule.period_start == monday)
                   .order_by(Schedule.lesson_number).all())
        data = [{
            'id': l.id,
            'day_of_week': l.day_of_week,
            'lesson_number': l.lesson_number,
            'subject': l.subject,
            'teacher': l.teacher,
            'location': l.location,
            'homework_id': l.homework.id if l.homework else None,
            'homework_text': l.homework.text if l.homework else '',
            'homework_files': len(l.homework.files) if l.homework else 0,
        } for l in lessons]
    finally:
        s.close()

    by_day = {d: [x for x in data if x['day_of_week'] == d] for d in DAY_NAMES}
    return render_template('admin/homework.html', by_day=by_day, days=DAY_NAMES,
                           monday=monday, week_end=monday + timedelta(days=5),
                           has_lessons=bool(data), offset=offset)


# Заполнение ДЗ перенесено в Telegram-бота (см. app/bot.py):
# страница /admin/homework — только просмотр.


# ─────────── Журнал изменений ───────────

@admin.route('/admin/changes')
@admin_required
def changes():
    s = Session()
    try:
        items = (s.query(ScheduleChange)
                 .order_by(ScheduleChange.detected_at.desc())
                 .limit(100).all())
        data = [{'detected_at': c.detected_at, 'changes': c.changes} for c in items]
    finally:
        s.close()
    return render_template('admin/changes.html', changes=data)


# ─────────── Обратная связь (пожелания пользователей) ───────────

@admin.route('/admin/feedback')
@admin_required
def feedback():
    s = Session()
    try:
        items = (s.query(Feedback)
                 .order_by(Feedback.created_at.desc())
                 .limit(200).all())
        data = [f.to_dict() for f in items]
        unread = sum(1 for f in data if not f['is_read'])
    finally:
        s.close()
    return render_template('admin/feedback.html', feedback=data, unread=unread)


@admin.route('/admin/feedback/<int:fid>/read', methods=['POST'])
@admin_required
def feedback_read(fid):
    s = Session()
    try:
        f = s.get(Feedback, fid)
        if f:
            f.is_read = True
            s.commit()
    finally:
        s.close()
    return redirect(url_for('admin.feedback'))


@admin.route('/admin/feedback/read_all', methods=['POST'])
@admin_required
def feedback_read_all():
    s = Session()
    try:
        s.query(Feedback).filter(Feedback.is_read.is_(False)).update(
            {Feedback.is_read: True}, synchronize_session=False)
        s.commit()
        flash('Все пожелания отмечены прочитанными', 'success')
    finally:
        s.close()
    return redirect(url_for('admin.feedback'))


@admin.route('/admin/feedback/<int:fid>/delete', methods=['POST'])
@admin_required
def feedback_delete(fid):
    s = Session()
    try:
        f = s.get(Feedback, fid)
        if f:
            s.delete(f)
            s.commit()
            flash('Пожелание удалено', 'success')
    finally:
        s.close()
    return redirect(url_for('admin.feedback'))


# ─────────── Расписание сессии ───────────

@admin.route('/admin/exams')
@admin_required
def exams():
    s = Session()
    try:
        items = s.query(Exam).order_by(Exam.date, Exam.time_start).all()
    finally:
        s.close()
    return render_template('admin/exams.html', exams=items, kinds=EXAM_KINDS,
                           csrf_token=_csrf_token())


@admin.route('/admin/exams/create', methods=['POST'])
@admin_required
def exams_create():
    if not _validate_csrf():
        return redirect(url_for('admin.exams'))

    subject = (request.form.get('subject') or '').strip()
    kind = request.form.get('kind') or 'экзамен'
    if kind not in EXAM_KINDS:
        kind = 'экзамен'
    if not subject:
        flash('Укажите предмет', 'error')
        return redirect(url_for('admin.exams'))
    date = _parse_date(request.form.get('date'), 'дату')
    if date is None:
        return redirect(url_for('admin.exams'))

    s = Session()
    try:
        s.add(Exam(
            subject=subject,
            kind=kind,
            date=date,
            time_start=_parse_time(request.form.get('time_start')),
            time_end=_parse_time(request.form.get('time_end')),
            location=(request.form.get('location') or '').strip() or None,
            teacher=(request.form.get('teacher') or '').strip() or None,
            notes=(request.form.get('notes') or '').strip() or None,
        ))
        s.commit()
        flash('Мероприятие добавлено в расписание сессии', 'success')
    finally:
        s.close()
    return redirect(url_for('admin.exams'))


@admin.route('/admin/exams/<int:eid>/edit', methods=['POST'])
@admin_required
def exams_edit(eid):
    if not _validate_csrf():
        return redirect(url_for('admin.exams'))

    s = Session()
    try:
        exam = s.get(Exam, eid)
        if not exam:
            flash('Мероприятие не найдено', 'error')
            return redirect(url_for('admin.exams'))

        subject = (request.form.get('subject') or '').strip()
        if not subject:
            flash('Укажите предмет', 'error')
            return redirect(url_for('admin.exams'))

        kind = request.form.get('kind') or 'экзамен'
        if kind not in EXAM_KINDS:
            kind = 'экзамен'
        date = _parse_date(request.form.get('date'), 'дату')
        if date is None:
            return redirect(url_for('admin.exams'))

        exam.subject = subject
        exam.kind = kind
        exam.date = date
        exam.time_start = _parse_time(request.form.get('time_start'))
        exam.time_end = _parse_time(request.form.get('time_end'))
        exam.location = (request.form.get('location') or '').strip() or None
        exam.teacher = (request.form.get('teacher') or '').strip() or None
        exam.notes = (request.form.get('notes') or '').strip() or None
        s.commit()
        flash('Мероприятие обновлено', 'success')
    finally:
        s.close()
    return redirect(url_for('admin.exams'))


@admin.route('/admin/exams/<int:eid>/delete', methods=['POST'])
@admin_required
def exams_delete(eid):
    if not _validate_csrf():
        return redirect(url_for('admin.exams'))

    s = Session()
    try:
        exam = s.get(Exam, eid)
        if exam:
            s.delete(exam)
            s.commit()
            flash('Мероприятие удалено', 'success')
    finally:
        s.close()
    return redirect(url_for('admin.exams'))


# ─────────── Дедлайны ───────────

@admin.route('/admin/deadlines')
@admin_required
def deadlines():
    s = Session()
    try:
        items = (s.query(Deadline)
                 .order_by(Deadline.is_done, Deadline.due_date, Deadline.due_time)
                 .all())
    finally:
        s.close()
    return render_template('admin/deadlines.html', deadlines=items,
                           today=datetime.now().date(),
                           csrf_token=_csrf_token())


@admin.route('/admin/deadlines/create', methods=['POST'])
@admin_required
def deadlines_create():
    if not _validate_csrf():
        return redirect(url_for('admin.deadlines'))

    subject = (request.form.get('subject') or '').strip()
    title = (request.form.get('title') or '').strip()
    if not subject or not title:
        flash('Укажите предмет и название дедлайна', 'error')
        return redirect(url_for('admin.deadlines'))

    due_date = _parse_date(request.form.get('due_date'), 'дату сдачи')
    if due_date is None:
        return redirect(url_for('admin.deadlines'))

    s = Session()
    try:
        s.add(Deadline(
            subject=subject,
            title=title,
            due_date=due_date,
            due_time=_parse_time(request.form.get('due_time')),
            notes=(request.form.get('notes') or '').strip() or None,
            is_done=request.form.get('is_done') == 'on',
        ))
        s.commit()
        flash('Дедлайн добавлен', 'success')
    finally:
        s.close()
    return redirect(url_for('admin.deadlines'))


@admin.route('/admin/deadlines/<int:did>/edit', methods=['POST'])
@admin_required
def deadlines_edit(did):
    if not _validate_csrf():
        return redirect(url_for('admin.deadlines'))

    s = Session()
    try:
        d = s.get(Deadline, did)
        if not d:
            flash('Дедлайн не найден', 'error')
            return redirect(url_for('admin.deadlines'))

        subject = (request.form.get('subject') or '').strip()
        title = (request.form.get('title') or '').strip()
        if not subject or not title:
            flash('Укажите предмет и название дедлайна', 'error')
            return redirect(url_for('admin.deadlines'))

        due_date = _parse_date(request.form.get('due_date'), 'дату сдачи')
        if due_date is None:
            return redirect(url_for('admin.deadlines'))

        d.subject = subject
        d.title = title
        d.due_date = due_date
        d.due_time = _parse_time(request.form.get('due_time'))
        d.notes = (request.form.get('notes') or '').strip() or None
        d.is_done = request.form.get('is_done') == 'on'
        s.commit()
        flash('Дедлайн обновлён', 'success')
    finally:
        s.close()
    return redirect(url_for('admin.deadlines'))


@admin.route('/admin/deadlines/<int:did>/toggle', methods=['POST'])
@admin_required
def deadlines_toggle(did):
    """Быстрое переключение статуса дедлайна без открытия формы."""
    if not _validate_csrf():
        return redirect(url_for('admin.deadlines'))

    s = Session()
    try:
        d = s.get(Deadline, did)
        if d:
            d.is_done = not d.is_done
            s.commit()
            flash('Статус дедлайна изменён', 'success')
    finally:
        s.close()
    return redirect(url_for('admin.deadlines'))


@admin.route('/admin/deadlines/<int:did>/delete', methods=['POST'])
@admin_required
def deadlines_delete(did):
    if not _validate_csrf():
        return redirect(url_for('admin.deadlines'))

    s = Session()
    try:
        d = s.get(Deadline, did)
        if d:
            s.delete(d)
            s.commit()
            flash('Дедлайн удалён', 'success')
    finally:
        s.close()
    return redirect(url_for('admin.deadlines'))


# ─────────── Общая информация о сессии ───────────

def _get_session_info(s):
    """Вернуть единственную запись SessionInfo; создать пустую при отсутствии."""
    info = s.get(SessionInfo, 1)
    if info is None:
        info = SessionInfo(id=1, text='', updated_at=datetime.now())
        s.add(info)
        s.commit()
        # после commit атрибуты экспирятся; refresh перезагружает их, чтобы
        # объект оставался читаемым после закрытия сессии (шаблон читает info.text)
        s.refresh(info)
    return info


@admin.route('/admin/session_info')
@admin_required
def session_info():
    s = Session()
    try:
        info = _get_session_info(s)
    finally:
        s.close()
    return render_template('admin/session_info.html', info=info,
                           csrf_token=_csrf_token())


@admin.route('/admin/session_info/save', methods=['POST'])
@admin_required
def session_info_save():
    if not _validate_csrf():
        return redirect(url_for('admin.session_info'))

    text = request.form.get('text') or ''
    s = Session()
    try:
        info = _get_session_info(s)
        info.text = text
        info.updated_at = datetime.now()
        info.updated_by = None
        s.commit()
        flash('Информация о сессии сохранена', 'success')
    finally:
        s.close()
    return redirect(url_for('admin.session_info'))
