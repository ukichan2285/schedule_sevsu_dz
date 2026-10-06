"""Админ-панель: авторизация, пользователи, домашние задания, журнал."""
from functools import wraps
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, session)
from sqlalchemy import func

from app.models import Session, User, Schedule, Homework, ScheduleChange

admin = Blueprint('admin', __name__)

DAY_NAMES = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']


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
        if role in ('admin', 'user'):
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

def _week_monday(d=None):
    d = d or datetime.now().date()
    return d - timedelta(days=d.weekday())


@admin.route('/admin/homework')
@login_required
def homework():
    offset = request.args.get('offset', 0, type=int)
    monday = _week_monday() + timedelta(weeks=offset)

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
