from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Date, ForeignKey, Boolean, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
import os

Base = declarative_base()

# Путь к базе данных
DATABASE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'schedule.db')
DATABASE_URL = f'sqlite:///{DATABASE_PATH}'

# Создание движка и сессии
engine = create_engine(DATABASE_URL, echo=False)
Session = sessionmaker(bind=engine)

def init_db():
    """Инициализация базы данных"""
    Base.metadata.create_all(engine)
    migrate()

def migrate():
    """Небольшие миграции для уже существующей SQLite-базы."""
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text('PRAGMA table_info(schedule)'))]
        if 'period_start' not in cols:
            conn.execute(text('ALTER TABLE schedule ADD COLUMN period_start DATE'))
            conn.commit()

        ucols = [row[1] for row in conn.execute(text('PRAGMA table_info(users)'))]
        if 'password_hash' not in ucols:
            conn.execute(text('ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)'))
            conn.commit()


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
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
    
    def to_dict(self):
        return {'id': self.id, 'schedule_id': self.schedule_id, 'text': self.text}

class ScheduleChange(Base):
    __tablename__ = 'schedule_changes'
    id = Column(Integer, primary_key=True)
    old_hash = Column(String(64))
    new_hash = Column(String(64))
    changes = Column(Text)
    detected_at = Column(DateTime)
