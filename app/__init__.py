from flask import Flask
from app.models import init_db

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'schedule-sevsu-secret-key-2024'
    
    # Инициализация БД
    init_db()
    
    # Регистрация blueprint'ов
    from app.routes import main
    app.register_blueprint(main)
    
    return app
