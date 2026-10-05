import logging
from telegram import Update, ForceReply
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

class ScheduleBot:
    def __init__(self, token, db_session):
        self.token = token
        self.db = db_session
        self.application = None
    
    def create_application(self):
        self.application = Application.builder().token(self.token).build()
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("get_schedule", self.get_schedule))
        self.application.add_handler(CommandHandler("get_changes", self.get_changes))
        self.application.add_handler(CommandHandler("set_homework", self.set_homework))
        self.application.add_handler(CommandHandler("admin_add_user", self.admin_add_user))
        self.application.add_handler(CommandHandler("admin_list_users", self.admin_list_users))
        return self.application
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await update.message.reply_text(f'Привет, {user.full_name}! 📚\nЯ бот для отслеживания расписания.\n\nДоступные команды:\n/get_schedule - расписание\n/set_homework <дата> <номер> <текст> - ДЗ\n/help - справка')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text('/get_schedule - расписание\n/set_homework <дата> <номер> <текст> - ДЗ\n/admin_add_user <username> - добавить пользователя\n/admin_list_users - список пользователей')
    
    async def get_schedule(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from app.models import Schedule
        from datetime import datetime, timedelta
        day_names = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']
        today = datetime.now()
        today_day = day_names[today.weekday()] if today.weekday() < 6 else 'Воскресенье'
        monday = today.date() - timedelta(days=today.weekday())
        schedule_items = (self.db.query(Schedule)
                          .filter(Schedule.day_of_week == today_day,
                                  Schedule.period_start == monday)
                          .order_by(Schedule.lesson_number).all())
        if not schedule_items:
            await update.message.reply_text('Расписание на сегодня отсутствует.')
            return
        message = f'*Расписание на {today_day}:\n'
        for item in schedule_items:
            message += f'\n#{item.lesson_number} *{item.subject}*\n  {item.teacher}\n  {item.location}\n'
            if item.homework:
                message += f'  📝 ДЗ: {item.homework.text}\n'
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def get_changes(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from app.models import ScheduleChange
        changes = self.db.query(ScheduleChange).order_by(ScheduleChange.detected_at.desc()).limit(5).all()
        if not changes:
            await update.message.reply_text('Изменений не обнаружено.')
            return
        message = '*Последние изменения:*\n'
        for c in changes:
            message += f'\n{c.detected_at}\n{c.changes}\n'
        await update.message.reply_text(message, parse_mode='Markdown')
    
    async def set_homework(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from app.models import Schedule, Homework
        from datetime import datetime
        user = update.effective_user
        text = " ".join(context.args) if context.args else ""
        if not text:
            await update.message.reply_text('Использование: /set_homework <дата> <номер> <текст>\nПример: /set_homework 05.10 1 Математика задачи 1-5')
            return
        try:
            parts = text.split(maxsplit=2)
            lesson_num = int(parts[1])
            homework_text = parts[2] if len(parts) > 2 else ""
            schedule_item = self.db.query(Schedule).filter(Schedule.lesson_number == lesson_num).first()
            if not schedule_item:
                await update.message.reply_text(f'Занятие #{lesson_num} не найдено.')
                return
            homework = self.db.query(Homework).filter(Homework.schedule_id == schedule_item.id).first()
            if homework:
                homework.text = homework_text
                homework.updated_at = datetime.now()
            else:
                homework = Homework(schedule_id=schedule_item.id, user_id=user.id, text=homework_text, created_at=datetime.now(), updated_at=datetime.now())
                self.db.add(homework)
            self.db.commit()
            await update.message.reply_text('✅ Домашнее задание записано!')
        except Exception as e:
            await update.message.reply_text(f'Ошибка: {e}')
    
    async def admin_add_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from app.models import User
        from datetime import datetime
        user = update.effective_user
        admin = self.db.query(User).filter(User.telegram_id == user.id, User.role == 'admin').first()
        if not admin:
            await update.message.reply_text('❌ У вас нет прав администратора!')
            return
        if not context.args:
            await update.message.reply_text('Использование: /admin_add_user <username>')
            return
        new_user = User(username=context.args[0], role='user', created_at=datetime.now(), is_active=True)
        self.db.add(new_user)
        self.db.commit()
        await update.message.reply_text(f'✅ Пользователь @{context.args[0]} создан!')
    
    async def admin_list_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        from app.models import User
        user = update.effective_user
        admin = self.db.query(User).filter(User.telegram_id == user.id, User.role == 'admin').first()
        if not admin:
            await update.message.reply_text('❌ У вас нет прав администратора!')
            return
        users = self.db.query(User).all()
        message = '*Список пользователей:*\n'
        for u in users:
            role = '👑' if u.role == 'admin' else '👤'
            message += f'{role} @{u.username} ({u.role})\n'
        await update.message.reply_text(message, parse_mode='Markdown')
    
    def run(self):
        app = self.create_application()
        print("Бот запущен...")
        app.run_polling()
