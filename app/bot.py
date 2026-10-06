"""Telegram-бот: расписание + заполнение ДЗ (текст/Markdown + фото).

Заполнять ДЗ может только администратор
(User.telegram_id == telegram id и role == 'admin').

Ввод ДЗ — через инлайн-кнопки: учебная неделя → день → пара.
Затем админ присылает текст (Markdown) и/или фото; всё сохраняется в БД,
а сайт показывает ДЗ с рендером Markdown и картинками.
"""
import logging
from datetime import datetime, timedelta, date
from html import escape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, ContextTypes, CallbackQueryHandler,
    MessageHandler, filters,
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
# httpx логирует полный URL запроса, а в нём — токен бота. Приглушаем.
logging.getLogger('httpx').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

DAY_NAMES = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']
DAY_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']
MAX_FILE_BYTES = 15 * 1024 * 1024  # лимит Bot API на скачивание файла ~20 МБ


def current_monday():
    d = datetime.now().date()
    return d - timedelta(days=d.weekday())


def fmt_week(monday):
    end = monday + timedelta(days=5)
    return f"{monday.strftime('%d.%m')}–{end.strftime('%d.%m.%Y')}"


class ScheduleBot:
    def __init__(self, token, db_session=None):
        self.token = token
        self.db = db_session  # оставлено для совместимости; хендлеры открывают свою сессию
        self.application = None

    # ────────── БД ──────────
    @staticmethod
    def _session():
        from app.models import Session
        return Session()

    @staticmethod
    def _user(session, tg_id):
        from app.models import User
        return session.query(User).filter(User.telegram_id == tg_id).first()

    @classmethod
    def _is_admin(cls, session, tg_id):
        u = cls._user(session, tg_id)
        return bool(u and u.role == 'admin' and u.is_active)

    @staticmethod
    def _get_or_create_homework(session, schedule_id, author_db_id):
        from app.models import Homework
        hw = session.query(Homework).filter(Homework.schedule_id == schedule_id).first()
        if hw is None:
            hw = Homework(schedule_id=schedule_id, user_id=author_db_id,
                          text='', created_at=datetime.now(), updated_at=datetime.now())
            session.add(hw)
            session.flush()
        return hw

    # ────────── Приложение ──────────
    def create_application(self):
        from app import config
        builder = Application.builder().token(self.token)
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

        self.application = application
        return application

    # ────────── Команды ──────────
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        u = update.effective_user
        logger.info('start: telegram_id=%s username=%s', u.id, u.username)
        session = self._session()
        try:
            is_admin = self._is_admin(session, u.id)
        finally:
            session.close()
        role = '👑 администратор' if is_admin else '👤 пользователь'
        keyboard = [[InlineKeyboardButton('✍️ Написать админу', callback_data='fb:start')]]
        await update.message.reply_text(
            f'Привет, <b>{escape(u.full_name)}</b>! 📚\n'
            f'Твой Telegram ID: <code>{u.id}</code> ({role})\n\n'
            'Команды:\n'
            '/get_schedule — расписание на сегодня\n'
            '/get_changes — последние изменения\n'
            '/homework — задать ДЗ (только админ)\n'
            '/feedback — написать пожелание админу\n'
            '/help — справка',
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard))

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            '<b>Справка</b>\n'
            '/get_schedule — расписание на сегодня\n'
            '/get_changes — последние изменения расписания\n'
            '/homework — задать ДЗ к паре (текст Markdown + фото)\n'
            '/feedback — отправить пожелание/идею администратору\n\n'
            'ДЗ заполняется кнопками: неделя → день → пара. '
            'Потом пришли текст и/или фото и нажми «✅ Готово».',
            parse_mode=ParseMode.HTML)

    async def get_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from app.models import Schedule
        session = self._session()
        try:
            today = datetime.now().date()
            monday = today - timedelta(days=today.weekday())
            day = DAY_NAMES[today.weekday()] if today.weekday() < 6 else 'Воскресенье'
            items = (session.query(Schedule)
                     .filter(Schedule.period_start == monday, Schedule.day_of_week == day)
                     .order_by(Schedule.lesson_number).all())
            lines = [f'<b>{escape(day)}</b>, {today.strftime("%d.%m.%Y")}']
            if not items:
                lines.append('Занятий нет.')
            for l in items:
                lines.append(f'\n<b>#{l.lesson_number} {escape(l.subject or "")}</b>')
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
        from app.models import ScheduleChange
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
        """Старт ввода ДЗ: выбор учебной недели."""
        u = update.effective_user
        session = self._session()
        try:
            if not self._is_admin(session, u.id):
                await update.message.reply_text('❌ Заполнять ДЗ может только администратор.')
                return
            from app.models import Schedule
            rows = (session.query(Schedule.period_start)
                    .filter(Schedule.period_start.isnot(None))
                    .distinct().order_by(Schedule.period_start).all())
            weeks = [r[0] for r in rows]
        finally:
            session.close()

        cm = current_monday()
        upcoming = [w for w in weeks if w >= cm - timedelta(days=7)][:8]
        weeks = upcoming or weeks[-8:]
        if not weeks:
            await update.message.reply_text('Расписание пустое — нечего заполнять.')
            return

        context.user_data.pop('hw_schedule_id', None)
        context.user_data.pop('feedback_mode', None)
        keyboard = []
        for w in weeks:
            label = fmt_week(w) + (' · текущая' if w == cm else '')
            keyboard.append([InlineKeyboardButton(label, callback_data=f'hw:w:{w.isoformat()}')])
        await update.message.reply_text('📚 Выбери учебную неделю:',
                                        reply_markup=InlineKeyboardMarkup(keyboard))

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

        from app.models import Feedback
        session = self._session()
        try:
            db_user = self._user(session, u.id)
            session.add(Feedback(
                user_id=db_user.id if db_user else None,
                telegram_id=u.id,
                username=u.username,
                full_name=u.full_name,
                text=text,
                created_at=datetime.now(),
                is_read=False,
            ))
            session.commit()
        finally:
            session.close()

        await self._notify_admins(context, u, text)
        await update.message.reply_text(
            '✅ Спасибо! Ваше сообщение отправлено администратору.')

    async def _notify_admins(self, context, user, text):
        """Переслать пожелание всем админам (из конфига и БД)."""
        from app import config
        from app.models import User
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

        body = (
            '💬 <b>Новое пожелание</b>\n'
            f'От: <b>{escape(user.full_name or "")}</b>'
            + (f' (@{escape(user.username)})' if user.username else '')
            + f'\nTelegram ID: <code>{user.id}</code>\n\n'
            + escape(text)
        )
        for admin_id in ids:
            try:
                await context.bot.send_message(chat_id=admin_id, text=body,
                                               parse_mode=ParseMode.HTML)
            except Exception as exc:  # noqa: BLE001
                logger.warning('Не удалось уведомить админа %s: %s', admin_id, exc)

    # ────────── Инлайн-кнопки ──────────
    async def on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from app.models import Schedule
        query = update.callback_query
        await query.answer()
        u = update.effective_user

        session = self._session()
        try:
            if not self._is_admin(session, u.id):
                await query.edit_message_text('❌ Нет прав.')
                return

            parts = query.data.split(':')
            kind = parts[1] if len(parts) > 1 else ''

            if kind == 'weeks':
                await self._send_weeks(query, context, session)

            elif kind == 'w':  # hw:w:<monday> — выбор дня
                monday = date.fromisoformat(parts[2])
                rows = (session.query(Schedule.day_of_week)
                        .filter(Schedule.period_start == monday).distinct().all())
                days = sorted({r[0] for r in rows if r[0]}, key=lambda d: DAY_NAMES.index(d) if d in DAY_NAMES else 99)
                keyboard = []
                for d in days:
                    short = DAY_SHORT[DAY_NAMES.index(d)] if d in DAY_NAMES else d
                    keyboard.append([InlineKeyboardButton(
                        f'{short} — {d}', callback_data=f'hw:d:{monday.isoformat()}:{DAY_NAMES.index(d)}')])
                keyboard.append([InlineKeyboardButton('« Недели', callback_data='hw:weeks')])
                await query.edit_message_text(
                    f'📅 Неделя {fmt_week(monday)}. Выбери день:',
                    reply_markup=InlineKeyboardMarkup(keyboard))

            elif kind == 'd':  # hw:d:<monday>:<day_index> — выбор пары
                monday = date.fromisoformat(parts[2])
                day = DAY_NAMES[int(parts[3])]
                lessons = (session.query(Schedule)
                           .filter(Schedule.period_start == monday, Schedule.day_of_week == day)
                           .order_by(Schedule.lesson_number).all())
                keyboard = []
                for l in lessons:
                    has = '📝 ' if (l.homework and (l.homework.text or l.homework.files)) else ''
                    label = f'{has}#{l.lesson_number} {l.subject or ""}'.strip()[:60]
                    keyboard.append([InlineKeyboardButton(label, callback_data=f'hw:l:{l.id}')])
                keyboard.append([InlineKeyboardButton('« Дни', callback_data=f'hw:w:{monday.isoformat()}')])
                await query.edit_message_text(
                    f'🗓 {day}, неделя {fmt_week(monday)}. Выбери пару:',
                    reply_markup=InlineKeyboardMarkup(keyboard))

            elif kind == 'l':  # hw:l:<schedule_id> — карточка ввода ДЗ
                schedule_id = int(parts[2])
                l = session.get(Schedule, schedule_id)
                if not l:
                    await query.edit_message_text('Занятие не найдено.')
                    return
                context.user_data['hw_schedule_id'] = schedule_id
                desc = ''
                hw = l.homework
                if hw and hw.text:
                    desc += f'\n\n<b>Текущий текст:</b>\n{escape(hw.text)}'
                if hw and hw.files:
                    desc += f'\n\n📎 вложений: {len(hw.files)}'
                keyboard = [
                    [InlineKeyboardButton('✅ Готово', callback_data='hw:done')],
                    [InlineKeyboardButton('🗑 Очистить ДЗ', callback_data=f'hw:clear:{schedule_id}')],
                    [InlineKeyboardButton('« Отмена', callback_data='hw:cancel')],
                ]
                await query.edit_message_text(
                    f'✍️ <b>#{l.lesson_number} {escape(l.subject or "")}</b>\n'
                    f'{escape(l.day_of_week or "")}, неделя {fmt_week(l.period_start) if l.period_start else "—"}\n\n'
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
                from app.models import Homework
                schedule_id = int(parts[2])
                hw = session.query(Homework).filter(Homework.schedule_id == schedule_id).first()
                if hw:
                    session.delete(hw)  # файлы удалятся каскадом
                    session.commit()
                context.user_data.pop('hw_schedule_id', None)
                await query.edit_message_text('🗑 ДЗ очищено (текст и вложения удалены).')
        finally:
            session.close()

    async def _send_weeks(self, query, context, session):
        from app.models import Schedule
        rows = (session.query(Schedule.period_start)
                .filter(Schedule.period_start.isnot(None))
                .distinct().order_by(Schedule.period_start).all())
        weeks = [r[0] for r in rows]
        cm = current_monday()
        upcoming = [w for w in weeks if w >= cm - timedelta(days=7)][:8]
        weeks = upcoming or weeks[-8:]
        keyboard = []
        for w in weeks:
            label = fmt_week(w) + (' · текущая' if w == cm else '')
            keyboard.append([InlineKeyboardButton(label, callback_data=f'hw:w:{w.isoformat()}')])
        await query.edit_message_text('📚 Выбери учебную неделю:',
                                      reply_markup=InlineKeyboardMarkup(keyboard))

    # ────────── Контент ДЗ: текст и файлы ──────────
    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            if not self._is_admin(session, u.id):
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
        from app.models import HomeworkFile
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
            if not self._is_admin(session, u.id):
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
