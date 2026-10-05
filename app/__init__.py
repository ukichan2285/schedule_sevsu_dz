from flask import Flask
from app.models import init_db
from app import config


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = config.SECRET_KEY

    # Инициализация БД + миграции
    init_db()

    # Регистрация blueprint'ов
    from app.routes import main
    from app.admin import admin
    app.register_blueprint(main)
    app.register_blueprint(admin)

    return app
