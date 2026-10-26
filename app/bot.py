"""Telegram-бот: расписание + заполнение ДЗ (текст/Markdown + фото).

Заполнять ДЗ может только администратор
(User.telegram_id == telegram id и role == 'admin').

Ввод ДЗ — через инлайн-кнопки: предмет → дата пары.
Затем админ присылает текст (Markdown) и/или фото; всё сохраняется в БД,
а сайт показывает ДЗ с рендером Markdown и картинками.
"""
import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta, date, time
from html import escape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, filters,
)
from telegram.request import HTTPXRequest

from app.ics_parser import DAY_NAMES, DAY_SHORT, day_name_for, week_monday
from app.models import Schedule, Homework, HomeworkFile, Feedback, ScheduleChange, Session, User


# Кнопки постоянного меню (появляются под полем ввода).
BTN_SCHEDULE = '📅 Расписание на сегодня'
BTN_HOMEWORK = '📝 Задать ДЗ'
BTN_FEEDBACK = '✍️ Пожелание админу'
BTN_HELP = '❓ Помощь'


def is_lecture(lesson):
    """Лекции ДЗ не заполняются: тип «лекция» (с подгруппой или без)."""
    return 'лекци' in (lesson.lesson_type or '').lower()


def main_menu(can_hw):
    """Постоянная клавиатура. «Задать ДЗ» — админам и заполняющим ДЗ."""
    rows = [[BTN_SCHEDULE], [BTN_FEEDBACK, BTN_HELP]]
    if can_hw:
        rows.insert(1, [BTN_HOMEWORK])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
# httpx логирует полный URL запроса, а в нём — токен бота. Приглушаем.
logging.getLogger('httpx').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 15 * 1024 * 1024  # лимит Bot API на скачивание файла ~20 МБ


class ScheduleBot:
    def __init__(self, token, db_session=None):
        self.token = token
        self.db = db_session  # оставлено для совместимости; хендлеры открывают свою сессию
        self.application = None

    # ────────── БД ──────────
    @staticmethod
    def _session():
        return Session()

    @staticmethod
    def _user(session, tg_id):
        return session.query(User).filter(User.telegram_id == tg_id).first()

    @classmethod
    def _is_admin(cls, session, tg_id):
        u = cls._user(session, tg_id)
        return bool(u and u.role == 'admin' and u.is_active)

    @classmethod
    def _can_homework(cls, session, tg_id):
        """Право заполнять ДЗ: админ или назначенный «заполняющий ДЗ»."""
        u = cls._user(session, tg_id)
        return bool(u and u.role in ('admin', 'homework') and u.is_active)

    @staticmethod
    def _get_or_create_homework(session, schedule_id, author_db_id):
        hw = session.query(Homework).filter(Homework.schedule_id == schedule_id).first()
        if hw is None:
            hw = Homework(schedule_id=schedule_id, user_id=author_db_id,
                          text='', created_at=datetime.now(), updated_at=datetime.now())
            session.add(hw)
            session.flush()
        return hw

    # ────────── Новый флоу ДЗ: предмет → дата ──────────
    @staticmethod
    def _subject_key(subject):
        """Стабильный короткий идентификатор предмета для callback-данных."""
        return hashlib.md5(subject.strip().lower().encode()).hexdigest()[:10]

    @classmethod
    def _resolve_subject(cls, session, key):
        """Найти предмет в БД по хешу (возвращает исходное значение из БД)."""
        rows = session.query(Schedule.subject).filter(Schedule.subject.isnot(None)).distinct().all()
        for (s,) in rows:
            if s and cls._subject_key(s) == key:
                return s
        return None

    @classmethod
    def _subjects(cls, session):
        """Все предметы с хотя бы одной не-лекцией, отсортированные по ближайшей будущей паре."""
        today = date.today()
        start = datetime.combine(today, time.min)
        all_lessons = (session.query(Schedule)
                       .filter(Schedule.subject.isnot(None), Schedule.date.isnot(None))
                       .order_by(Schedule.date, Schedule.lesson_number).all())
        info = {}
        for l in all_lessons:
            s = (l.subject or '').strip()
            if not s or is_lecture(l):
                continue
            if s not in info:
                info[s] = {'nearest_future': None}
            if l.date >= start and info[s]['nearest_future'] is None:
                info[s]['nearest_future'] = l.date.date() if isinstance(l.date, datetime) else l.date
        subjects = list(info.keys())
        subjects.sort(key=lambda s: (info[s]['nearest_future'] or date.max, s))
        return subjects

    @staticmethod
    def _subject_lessons(session, subject, past=False, limit=None):
        """Не-лекции предмета: будущие (до +8 недель) или прошедшие (limit штук)."""
        today = date.today()
        start = datetime.combine(today, time.min)
        query = (session.query(Schedule)
                 .filter(Schedule.subject == subject, Schedule.date.isnot(None)))
        if past:
            query = (query.filter(Schedule.date < start)
                     .order_by(Schedule.date.desc(), Schedule.lesson_number.desc()))
        else:
            end = datetime.combine(today + timedelta(weeks=8), time.max)
            query = (query.filter(Schedule.date >= start, Schedule.date <= end)
                     .order_by(Schedule.date, Schedule.lesson_number))
        lessons = [l for l in query.all() if not is_lecture(l)]
        if limit:
            lessons = lessons[:limit]
        return lessons

    @staticmethod
    def _lesson_button_label(l):
        """Подпись кнопки пары: дата, день, номер, подгруппа, время, пометки."""
        has = '📝 ' if (l.homework and (l.homework.text or l.homework.files)) else ''
        d = l.date.date() if isinstance(l.date, datetime) else l.date
        short = (DAY_SHORT[DAY_NAMES.index(l.day_of_week)]
                 if l.day_of_week in DAY_NAMES else (l.day_of_week or '')[:2])
        # У физкультуры пары идут подгруппами: без пометки кнопки неразличимы
        m = re.search(r'подгр\.\s*(\d+)', l.lesson_type or '')
        sub = f' · подгр.{m.group(1)}' if m else ''
        label = f"{has}{d.strftime('%d.%m')} ({short}) · #{l.lesson_number}{sub}"
        if l.time_start:
            label += f" · {l.time_start}"
        today = date.today()
        if d == today:
            label += ' · сегодня'
        elif d == today + timedelta(days=1):
            label += ' · завтра'
        return label[:60]

    # ────────── Приложение ──────────
    def create_application(self):
        from app import config
        # Соединение с Telegram на РФ-хостинге иногда рвётся (ConnectTimeout).
        # Поднимаем таймауты и добавляем повторы (см. _send_telegram / _resend_loop).
        request = HTTPXRequest(connect_timeout=10.0, read_timeout=20.0,
                               write_timeout=20.0, pool_timeout=5.0)
        builder = Application.builder().token(self.token).request(request)
        if config.TELEGRAM_PROXY:
            builder = builder.proxy(config.TELEGRAM_PROXY).get_updates_proxy(config.TELEGRAM_PROXY)
        application = builder.build()

        application.add_handler(CommandHandler('start', self.start))
        application.add_handler(CommandHandler('help', self.help_command))
        application.add_handler(CommandHandler(['get_schedule', 'schedule'], self.get_schedule))
        application.add_handler(CommandHandler(['get_changes', 'changes'], self.get_changes))
        application.add_handler(CommandHandler(['homework', 'set_homework', 'dz'], self.homework))
        application.add_handler(CommandHandler(['feedback', 'suggest', 'idea'], self.feedback))
        application.add_handler(CommandHandler('done', self.done))
        application.add_handler(CommandHandler('cancel', self.cancel))

        application.add_handler(CallbackQueryHandler(self.on_callback, pattern=r'^hw:'))
        application.add_handler(CallbackQueryHandler(self.on_feedback_callback, pattern=r'^fb:'))
        application.add_handler(MessageHandler(filters.PHOTO, self.on_photo))
        application.add_handler(MessageHandler(filters.Document.IMAGE, self.on_document))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        application.add_error_handler(self.on_error)

        # После старта запускаем фоновую досылку неотправленных пожеланий
        application.post_init = self._post_init

        self.application = application
        return application

    async def _post_init(self, application):
        try:
            application.create_task(self._resend_loop(application))
            logger.info('Фоновая досылка пожеланий запущена')
        except Exception as exc:  # noqa: BLE001
            logger.warning('Не удалось запустить досылку пожеланий: %s', exc)

    async def on_error(self, update, context):
        logger.warning('Ошибка обработки запроса: %s', context.error)

    # ────────── Команды ──────────
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        u = update.effective_user
        logger.info('start: telegram_id=%s username=%s', u.id, u.username)
        session = self._session()
        try:
            is_admin = self._is_admin(session, u.id)
            can_hw = self._can_homework(session, u.id)
        finally:
            session.close()
        if is_admin:
            role = '👑 администратор'
        elif can_hw:
            role = '📝 заполняющий ДЗ'
        else:
            role = '👤 пользователь'
        await update.message.reply_text(
            f'Привет, <b>{escape(u.full_name)}</b>! 📚\n'
            f'Твой Telegram ID: <code>{u.id}</code> ({role})\n\n'
            'Выбери действие на кнопках внизу.',
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(can_hw))

    # ────────── Кнопки меню → существующие действия ──────────
    async def _menu_action(self, update, context, text):
        """Выполнить действие по нажатой кнопке. True, если текст был кнопкой."""
        if text == BTN_SCHEDULE:
            await self.get_schedule(update, context)
        elif text == BTN_HOMEWORK:
            await self.homework(update, context)
        elif text == BTN_FEEDBACK:
            await self.feedback(update, context)
        elif text == BTN_HELP:
            await self.help_command(update, context)
        else:
            return False
        return True

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            '<b>Справка</b>\n'
            '/get_schedule — расписание на сегодня\n'
            '/get_changes — последние изменения расписания\n'
            '/homework — задать ДЗ к паре (текст Markdown + фото)\n'
            '/feedback — отправить пожелание/идею администратору\n\n'
            'ДЗ заполняется кнопками: предмет → пара. '
            'Потом пришли текст и/или фото и нажми «✅ Готово».',
            parse_mode=ParseMode.HTML)

    async def get_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        session = self._session()
        try:
            today = datetime.now().date()
            monday = week_monday(today)
            day = day_name_for(today) or 'Воскресенье'
            items = (session.query(Schedule)
                     .filter(Schedule.period_start == monday, Schedule.day_of_week == day)
                     .order_by(Schedule.lesson_number).all())
            lines = [f'<b>{escape(day)}</b>, {today.strftime("%d.%m.%Y")}']
            if not items:
                lines.append('Занятий нет.')
            for l in items:
                time_part = f' ({l.time_range})' if l.time_range else ''
                lines.append(f'\n<b>#{l.lesson_number}{time_part} {escape(l.subject or "")}</b>')
                if l.teacher:
                    lines.append(f'  👤 {escape(l.teacher)}')
                if l.location:
                    lines.append(f'  📍 {escape(l.location)}')
                if l.homework and l.homework.text:
                    lines.append(f'  📝 ДЗ: {escape(l.homework.text)}')
        finally:
            session.close()
        await update.message.reply_text('\n'.join(lines), parse_mode=ParseMode.HTML)

    async def get_changes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        session = self._session()
        try:
            changes = (session.query(ScheduleChange)
                       .order_by(ScheduleChange.detected_at.desc()).limit(5).all())
            if not changes:
                await update.message.reply_text('Изменений не обнаружено.')
                return
            lines = ['<b>Последние изменения:</b>']
            for c in changes:
                when = c.detected_at.strftime('%d.%m %H:%M') if c.detected_at else ''
                lines.append(f'\n{when}\n{escape(c.changes or "")}')
        finally:
            session.close()
        await update.message.reply_text('\n'.join(lines), parse_mode=ParseMode.HTML)

    async def homework(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старт ввода ДЗ: выбор предмета."""
        u = update.effective_user
        session = self._session()
        try:
            if not self._can_homework(session, u.id):
                await update.message.reply_text('❌ Заполнять ДЗ может только администратор.')
                return
            subjects = self._subjects(session)
        finally:
            session.close()

        context.user_data.pop('hw_schedule_id', None)
        context.user_data.pop('feedback_mode', None)

        if not subjects:
            await update.message.reply_text('Расписание пустое — нечего заполнять.')
            return

        keyboard = []
        for s in subjects:
            key = self._subject_key(s)
            keyboard.append([InlineKeyboardButton(s[:60], callback_data=f'hw:subj:{key}')])
        await update.message.reply_text(
            '📚 <b>Выбери предмет</b>\nОтсчёт пар идёт от сегодняшнего дня.',
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML)

    async def done(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data.pop('hw_schedule_id', None)
        await update.message.reply_text('✅ Готово. ДЗ сохранено.')

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        had_feedback = context.user_data.pop('feedback_mode', None)
        context.user_data.pop('hw_schedule_id', None)
        await update.message.reply_text('Отменено.' if not had_feedback else 'Отменено. Пожелание не отправлено.')

    # ────────── Обратная связь (пожелания админу) ──────────
    async def feedback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старт режима отправки пожелания администратору."""
        context.user_data.pop('hw_schedule_id', None)
        context.user_data['feedback_mode'] = True
        await update.message.reply_text(
            '✍️ Напишите одним сообщением ваше пожелание или предложение '
            'по боту и приложению — оно уйдёт администратору.\n\n'
            'Отмена — /cancel.',
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton('« Отмена', callback_data='fb:cancel')]]),
            parse_mode=ParseMode.HTML)

    async def on_feedback_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        parts = query.data.split(':')
        kind = parts[1] if len(parts) > 1 else ''

        if kind == 'start':
            context.user_data.pop('hw_schedule_id', None)
            context.user_data['feedback_mode'] = True
            await query.edit_message_text(
                '✍️ Напишите одним сообщением ваше пожелание или предложение '
                'по боту и приложению — оно уйдёт администратору.\n\n'
                'Отмена — /cancel.',
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton('« Отмена', callback_data='fb:cancel')]]),
                parse_mode=ParseMode.HTML)

        elif kind == 'cancel':
            context.user_data.pop('feedback_mode', None)
            await query.edit_message_text('Отменено. Пожелание не отправлено.')

    async def _handle_feedback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Сохранить пожелание и уведомить администраторов."""
        u = update.effective_user
        text = (update.message.text or '').strip()
        if not text:
            await update.message.reply_text('Пустое сообщение — напишите текст пожелания.')
            return
        if len(text) > 4000:
            text = text[:4000]

        context.user_data.pop('feedback_mode', None)

        session = self._session()
        try:
            db_user = self._user(session, u.id)
            fb = Feedback(
                user_id=db_user.id if db_user else None,
                telegram_id=u.id,
                username=u.username,
                full_name=u.full_name,
                text=text,
                created_at=datetime.now(),
                is_read=False,
                notified=False,
            )
            session.add(fb)
            session.commit()
            fb_id = fb.id
        finally:
            session.close()

        # Подтверждаем пользователю сразу — сохранение уже прошло.
        try:
            await update.message.reply_text(
                '✅ Спасибо! Сообщение сохранено и отправлено администратору.')
        except Exception as exc:  # noqa: BLE001
            logger.warning('Не удалось ответить пользователю %s: %s', u.id, exc)

        # Доставку админу делаем отдельной задачей: при обрыве связи Telegram
        # будут повторы, а фоновая досылка (_resend_loop) дошлёт позже.
        try:
            context.application.create_task(self._deliver_feedback(context.bot, fb_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning('Не удалось запустить доставку пожелания %s: %s', fb_id, exc)

    # ────────── Доставка пожеланий админу (с повторами) ──────────
    def _admin_ids(self):
        """ID админов: из конфига и из БД (role='admin')."""
        from app import config
        ids = set()
        for value in (config.ADMIN_TELEGRAM_ID, config.TELEGRAM_ADMIN_ID):
            try:
                if value:
                    ids.add(int(value))
            except (TypeError, ValueError):
                pass
        session = self._session()
        try:
            for (tid,) in (session.query(User.telegram_id)
                           .filter(User.role == 'admin', User.telegram_id.isnot(None)).all()):
                if tid:
                    ids.add(int(tid))
        finally:
            session.close()
        return ids

    @staticmethod
    def _feedback_body(full_name, username, tg_id, text):
        return (
            '💬 <b>Новое пожелание</b>\n'
            f'От: <b>{escape(full_name or "")}</b>'
            + (f' (@{escape(username)})' if username else '')
            + f'\nTelegram ID: <code>{tg_id}</code>\n\n'
            + escape(text)
        )

    async def _send_telegram(self, bot, chat_id, text, attempts=4):
        """send_message с повторами при сетевых сбоях. True, если доставлено."""
        from telegram.error import RetryAfter, TimedOut, NetworkError
        for n in range(attempts):
            try:
                await bot.send_message(chat_id=chat_id, text=text,
                                       parse_mode=ParseMode.HTML)
                return True
            except RetryAfter as exc:
                delay = float(getattr(exc, 'retry_after', 3) or 3) + 1
                logger.warning('Telegram лимит для %s, пауза %.0fс', chat_id, delay)
                await asyncio.sleep(delay)
            except (TimedOut, NetworkError) as exc:
                if n >= attempts - 1:
                    logger.warning('Не удалось отправить в чат %s после %d попыток: %s',
                                   chat_id, attempts, exc)
                    return False
                await asyncio.sleep(1.5 * (2 ** n))
            except Exception as exc:  # noqa: BLE001
                logger.warning('Ошибка отправки в чат %s: %s', chat_id, exc)
                return False
        return False

    async def _deliver_feedback(self, bot, fb_id):
        """Отправить одно пожелание админам; при успехе пометить notified."""
        from app.models import Feedback
        session = self._session()
        try:
            fb = session.get(Feedback, fb_id)
            if not fb or fb.notified:
                return
            body = self._feedback_body(fb.full_name, fb.username, fb.telegram_id, fb.text)
        finally:
            session.close()

        delivered = False
        for admin_id in self._admin_ids():
            if await self._send_telegram(bot, admin_id, body):
                delivered = True

        if delivered:
            session = self._session()
            try:
                fb = session.get(Feedback, fb_id)
                if fb and not fb.notified:
                    fb.notified = True
                    fb.notified_at = datetime.now()
                    session.commit()
            finally:
                session.close()

    async def _resend_loop(self, application):
        """Периодически дошлёт пожелания, которые не ушли из-за сбоя сети."""
        await asyncio.sleep(15)
        while True:
            try:
                await self._resend_pending(application.bot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning('Ошибка фоновой досылки пожеланий: %s', exc)
            await asyncio.sleep(60)

    async def _resend_pending(self, bot):
        from sqlalchemy import or_
        from app.models import Feedback
        session = self._session()
        try:
            pending = (session.query(Feedback)
                       .filter(or_(Feedback.notified.is_(False),
                                   Feedback.notified.is_(None)))
                       .order_by(Feedback.created_at).limit(20).all())
            ids = [f.id for f in pending]
        finally:
            session.close()

        if ids:
            logger.info('Досылка пожеланий: %s', ids)
        for fid in ids:
            await self._deliver_feedback(bot, fid)

    # ────────── Инлайн-кнопки ──────────
    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        u = update.effective_user

        session = self._session()
        try:
            if not self._can_homework(session, u.id):
                await query.edit_message_text('❌ Нет прав.')
                return

            parts = query.data.split(':')
            kind = parts[1] if len(parts) > 1 else ''

            if kind == 'subjects':  # hw:subjects — список предметов
                await self._send_subjects(query, session)

            elif kind == 'subj':  # hw:subj:<key> — будущие пары предмета
                key = parts[2]
                subject = self._resolve_subject(session, key)
                if not subject:
                    await query.edit_message_text('Предмет не найден.')
                    return
                lessons = self._subject_lessons(session, subject, past=False)
                keyboard = []
                for l in lessons:
                    keyboard.append([InlineKeyboardButton(
                        self._lesson_button_label(l), callback_data=f'hw:l:{l.id}')])
                if not lessons:
                    past_lessons = self._subject_lessons(session, subject, past=True)
                    if past_lessons:
                        text = 'Будущих пар по этому предмету нет.'
                        keyboard.append([InlineKeyboardButton(
                            '📜 Прошедшие пары', callback_data=f'hw:past:{key}')])
                    else:
                        text = 'Для этого предмета нет практик в расписании.'
                    keyboard.append([InlineKeyboardButton(
                        '« Предметы', callback_data='hw:subjects')])
                else:
                    text = f'📅 <b>{escape(subject)}</b>\nВыбери пару (только ПЗ, отсчёт от сегодня):'
                    keyboard.append([InlineKeyboardButton(
                        '📜 Прошедшие пары', callback_data=f'hw:past:{key}')])
                    keyboard.append([InlineKeyboardButton(
                        '« Предметы', callback_data='hw:subjects')])
                await query.edit_message_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML)

            elif kind == 'past':  # hw:past:<key> — прошедшие пары предмета
                key = parts[2]
                subject = self._resolve_subject(session, key)
                if not subject:
                    await query.edit_message_text('Предмет не найден.')
                    return
                lessons = self._subject_lessons(session, subject, past=True, limit=6)
                keyboard = []
                for l in lessons:
                    keyboard.append([InlineKeyboardButton(
                        self._lesson_button_label(l), callback_data=f'hw:l:{l.id}')])
                keyboard.append([InlineKeyboardButton(
                    '« К датам', callback_data=f'hw:subj:{key}')])
                text = (f'📜 <b>{escape(subject)}</b>\nПрошедшие пары:'
                        if lessons
                        else f'📜 <b>{escape(subject)}</b>\nПрошедших пар нет.')
                await query.edit_message_text(
                    text,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML)

            elif kind == 'l':  # hw:l:<schedule_id> — карточка ввода ДЗ
                schedule_id = int(parts[2])
                l = session.get(Schedule, schedule_id)
                if not l:
                    await query.edit_message_text('Занятие не найдено.')
                    return
                if is_lecture(l):
                    await query.edit_message_text('Для лекций ДЗ не заполняется.')
                    return
                context.user_data['hw_schedule_id'] = schedule_id
                desc = ''
                hw = l.homework
                if hw and hw.text:
                    desc += f'\n\n<b>Текущий текст:</b>\n{escape(hw.text)}'
                if hw and hw.files:
                    desc += f'\n\n📎 вложений: {len(hw.files)}'
                key = self._subject_key(l.subject or '')
                keyboard = [
                    [InlineKeyboardButton('✅ Готово', callback_data='hw:done')],
                    [InlineKeyboardButton('🗑 Очистить ДЗ', callback_data=f'hw:clear:{schedule_id}')],
                    [InlineKeyboardButton('« К датам', callback_data=f'hw:subj:{key}')],
                ]
                await query.edit_message_text(
                    f'✍️ <b>#{l.lesson_number} {escape(l.subject or "")}</b>\n'
                    f'{escape(l.day_of_week or "")}, {l.date.strftime("%d.%m.%Y") if l.date else ""}\n\n'
                    'Пришли текст ДЗ (Markdown: **жирный**, *курсив*, `код`, списки) '
                    'и/или фото. Можно несколькими сообщениями.'
                    + desc,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.HTML)

            elif kind == 'done':
                context.user_data.pop('hw_schedule_id', None)
                await query.edit_message_text('✅ ДЗ сохранено.')

            elif kind == 'cancel':
                context.user_data.pop('hw_schedule_id', None)
                await query.edit_message_text('Отменено.')

            elif kind == 'clear':
                schedule_id = int(parts[2])
                hw = session.query(Homework).filter(Homework.schedule_id == schedule_id).first()
                if hw:
                    session.delete(hw)  # файлы удалятся каскадом
                    session.commit()
                context.user_data.pop('hw_schedule_id', None)
                await query.edit_message_text('🗑 ДЗ очищено (текст и вложения удалены).')
        finally:
            session.close()

    async def _send_subjects(self, query, session):
        """Отправить/обновить список предметов."""
        subjects = self._subjects(session)
        if not subjects:
            await query.edit_message_text('Расписание пустое — нечего заполнять.')
            return
        keyboard = []
        for s in subjects:
            key = self._subject_key(s)
            keyboard.append([InlineKeyboardButton(s[:60], callback_data=f'hw:subj:{key}')])
        await query.edit_message_text(
            '📚 <b>Выбери предмет</b>\nОтсчёт пар идёт от сегодняшнего дня.',
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML)

    # ────────── Контент ДЗ: текст и файлы ──────────
    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (update.message.text or '').strip()
        # Нажатие кнопки меню важнее любого режима: сбрасываем ввод и выполняем действие.
        if text in (BTN_SCHEDULE, BTN_HOMEWORK, BTN_FEEDBACK, BTN_HELP):
            context.user_data.pop('hw_schedule_id', None)
            context.user_data.pop('feedback_mode', None)
            await self._menu_action(update, context, text)
            return
        if context.user_data.get('feedback_mode'):
            await self._handle_feedback(update, context)
            return
        schedule_id = context.user_data.get('hw_schedule_id')
        if not schedule_id:
            return  # обычное сообщение вне режима ввода ДЗ — игнорируем
        u = update.effective_user
        text = update.message.text or ''
        session = self._session()
        try:
            if not self._can_homework(session, u.id):
                return
            db_user = self._user(session, u.id)
            hw = self._get_or_create_homework(session, schedule_id, db_user.id)
            hw.text = text
            hw.updated_at = datetime.now()
            session.commit()
        finally:
            session.close()
        await update.message.reply_text('📝 Текст сохранён. Пришли фото или нажми «✅ Готово».')

    async def on_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        schedule_id = context.user_data.get('hw_schedule_id')
        if not schedule_id:
            return
        photo = update.message.photo[-1]  # максимальный размер
        await self._save_attachment(update, context, schedule_id, photo.file_id,
                                    'image/jpeg', f'photo_{photo.file_unique_id}.jpg')

    async def on_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        schedule_id = context.user_data.get('hw_schedule_id')
        if not schedule_id:
            return
        doc = update.message.document
        await self._save_attachment(update, context, schedule_id, doc.file_id,
                                    doc.mime_type or 'application/octet-stream',
                                    doc.file_name or f'doc_{doc.file_unique_id}')

    async def _save_attachment(self, update, context, schedule_id, file_id, mime, name):
        u = update.effective_user
        try:
            tg_file = await context.bot.get_file(file_id)
            data = bytes(await tg_file.download_as_bytearray())
        except Exception as exc:  # noqa: BLE001
            await update.message.reply_text(f'⚠️ Не удалось скачать файл: {exc}')
            return
        if len(data) > MAX_FILE_BYTES:
            await update.message.reply_text('⚠️ Файл слишком большой (макс. 15 МБ).')
            return
        session = self._session()
        try:
            if not self._can_homework(session, u.id):
                return
            db_user = self._user(session, u.id)
            hw = self._get_or_create_homework(session, schedule_id, db_user.id)
            session.add(HomeworkFile(homework_id=hw.id, file_name=name, mime_type=mime,
                                     size=len(data), data=data, created_at=datetime.now()))
            caption = getattr(update.message, 'caption', None)
            if caption:
                hw.text = caption
                hw.updated_at = datetime.now()
            session.commit()
            total = session.query(HomeworkFile).filter(HomeworkFile.homework_id == hw.id).count()
        finally:
            session.close()
        await update.message.reply_text(f'📎 Вложение добавлено (всего: {total}).')

    def run(self):
        app = self.create_application()
        print('Бот запущен...')
        app.run_polling()
