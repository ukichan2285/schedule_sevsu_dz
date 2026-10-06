from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Text, DateTime, Date, ForeignKey, Boolean, LargeBinary, text, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, deferred
from datetime import datetime
import os

from app import config

Base = declarative_base()


def _resolve_db_url():
    """DATABASE_URL (Postgres/Render) или SQLite-файл."""
    url = (config.DATABASE_URL or '').strip()
    if url:
        # Render отдаёт postgres://, SQLAlchemy хочет postgresql://
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql://', 1)
        # SQLAlchemy 2.1+ по умолчанию использует psycopg3 — фиксируем драйвер явно
        if url.startswith('postgresql://'):
            url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
        return url

    path = (config.SCHEDULE_DB_PATH or '').strip()
    if not path:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'data', 'schedule.db')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return f'sqlite:///{path}'


DATABASE_URL = _resolve_db_url()

# SQLite в связке с потоками (gunicorn) требует check_same_thread=False
if DATABASE_URL.startswith('sqlite'):
    engine = create_engine(DATABASE_URL, echo=False,
                           connect_args={'check_same_thread': False})
else:
    engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True)

Session = sessionmaker(bind=engine)


def init_db():
    """Инициализация базы данных"""
    Base.metadata.create_all(engine)
    migrate()


def migrate():
    """Добавить недостающие колонки (работает и в SQLite, и в PostgreSQL)."""
    insp = inspect(engine)
    tables = insp.get_table_names()

    def ensure_column(table, column, ddl):
        if table not in tables:
            return
        cols = [c['name'] for c in insp.get_columns(table)]
        if column not in cols:
            with engine.begin() as conn:
                conn.execute(text(ddl))

    ensure_column('schedule', 'period_start',
                  'ALTER TABLE schedule ADD COLUMN period_start DATE')
    ensure_column('users', 'password_hash',
                  'ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)')
    ensure_column('homework_files', 'size',
                  'ALTER TABLE homework_files ADD COLUMN size INTEGER')


def ensure_admin():
    """Создать/обновить первого администратора. Идемпотентно и потокобезопасно.

    Вызывается при старте приложения (в т.ч. gunicorn на Render), а не только
    из run.py. При нескольких воркерах возможна гонка — ловим IntegrityError.
    """
    from datetime import datetime
    session = Session()
    try:
        user = session.query(User).filter(User.username == config.ADMIN_USERNAME).first()
        if user is None:
            user = User(
                telegram_id=config.ADMIN_TELEGRAM_ID,
                username=config.ADMIN_USERNAME,
                role='admin',
                created_at=datetime.now(),
                is_active=True,
            )
            user.set_password(config.ADMIN_PASSWORD)
            session.add(user)
            try:
                session.commit()
                print(f'✅ Админ создан: {config.ADMIN_USERNAME}')
            except IntegrityError:
                session.rollback()
        else:
            user.role = 'admin'
            user.is_active = True
            if not user.password_hash:
                user.set_password(config.ADMIN_PASSWORD)
                session.commit()
                print(f'✅ Админу {config.ADMIN_USERNAME} установлен пароль')
    finally:
        session.close()


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True)  # NULL — для пользователей, созданных в вебе/боте
    username = Column(String(100), unique=True)
    first_name = Column(String(100))
    last_name = Column(String(100))
    password_hash = Column(String(255))
    role = Column(String(20), default='user')
    created_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
    homework_assignments = relationship('Homework', back_populates='author')

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def display_name(self):
        return self.username or self.first_name or f'user{self.id}'

    def to_dict(self):
        return {'id': self.id, 'telegram_id': self.telegram_id, 'username': self.username, 'role': self.role, 'is_active': self.is_active}

class Schedule(Base):
    __tablename__ = 'schedule'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, nullable=False)
    period_start = Column(Date)          # понедельник учебной недели
    day_of_week = Column(String(20))
    lesson_number = Column(Integer)
    subject = Column(String(200))
    teacher = Column(String(200))
    location = Column(String(100))
    lesson_type = Column(String(50))
    hash = Column(String(64))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    homework = relationship('Homework', back_populates='schedule', uselist=False,
                            cascade='all, delete-orphan')
    
    def to_dict(self):
        return {'id': self.id, 'day_of_week': self.day_of_week, 'lesson_number': self.lesson_number, 'subject': self.subject, 'teacher': self.teacher, 'location': self.location}

class Homework(Base):
    __tablename__ = 'homework'
    id = Column(Integer, primary_key=True)
    schedule_id = Column(Integer, ForeignKey('schedule.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    text = Column(Text)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    schedule = relationship('Schedule', back_populates='homework')
    author = relationship('User', back_populates='homework_assignments')
    files = relationship('HomeworkFile', back_populates='homework',
                         cascade='all, delete-orphan', order_by='HomeworkFile.id')

    def to_dict(self):
        return {
            'id': self.id,
            'schedule_id': self.schedule_id,
            'text': self.text,
            'files': [f.to_dict() for f in self.files],
        }


class HomeworkFile(Base):
    """Вложение к ДЗ (фото/документ). Данные лежат в БД (Postgres bytea)."""
    __tablename__ = 'homework_files'
    id = Column(Integer, primary_key=True)
    homework_id = Column(Integer, ForeignKey('homework.id', ondelete='CASCADE'), nullable=False)
    file_name = Column(String(255))
    mime_type = Column(String(100))
    size = Column(Integer)
    # data отложенная: страницы со списком занятий не тянут байты картинок
    data = deferred(Column(LargeBinary))
    created_at = Column(DateTime)
    homework = relationship('Homework', back_populates='files')

    def to_dict(self):
        return {
            'id': self.id,
            'file_name': self.file_name,
            'mime_type': self.mime_type,
            'size': self.size or 0,
        }

class ScheduleChange(Base):
    __tablename__ = 'schedule_changes'
    id = Column(Integer, primary_key=True)
    old_hash = Column(String(64))
    new_hash = Column(String(64))
    changes = Column(Text)
    detected_at = Column(DateTime)
