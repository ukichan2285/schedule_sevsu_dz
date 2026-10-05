#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import config
from app.bot import ScheduleBot
from app.models import Session, init_db

init_db()

token = config.TELEGRAM_BOT_TOKEN or '8887484529:AAEWm234H5kWwj8mUTfJ0ogpm7N863k7i1k'
bot = ScheduleBot(token, Session())
bot.run()
