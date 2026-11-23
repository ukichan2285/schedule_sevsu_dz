from flask import Flask
from app.models import init_db, ensure_admin, Announcement, Session
from app import config


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = config.SECRET_KEY
    if config.HTTPS_ENABLED:
        from werkzeug.middleware.proxy_fix import ProxyFix
        # За Apache/uWSGI: доверяем X-Forwarded-Proto, чтобы url_for и редиректы давали https
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
        app.config.update(
            PREFERRED_URL_SCHEME='https',
            SESSION_COOKIE_SECURE=True,
            REMEMBER_COOKIE_SECURE=True,
        )

    # Инициализация БД + миграции
    init_db()

    # Первый администратор создаётся при старте (важно для gunicorn/Render)
    ensure_admin()

    # Регистрация blueprint'ов
    from app.routes import main
    from app.admin import admin
    app.register_blueprint(main)
    app.register_blueprint(admin)

    # Фильтр для рендера Markdown из ДЗ: в шаблонах {{ text | md }}
    from app.markdown_render import render as render_md
    app.add_template_filter(render_md, 'md')

    # Серверное «сейчас» для живой шкалы времени: JS на странице считает
    # расхождение своих часов с сервером и тикает по этому смещению, чтобы
    # шкала не расходилась с расписанием при другом часовом поясе браузера.
    from datetime import datetime as _datetime

    @app.context_processor
    def _inject_server_now():
        return {'server_now': _datetime.now().isoformat(timespec='seconds')}

    # Активные объявления для баннера на всех страницах
    @app.context_processor
    def _inject_announcements():
        try:
            s = Session()
            try:
                items = (s.query(Announcement)
                         .filter(Announcement.is_active.is_(True))
                         .order_by(Announcement.created_at.desc())
                         .all())
                return {'announcements': items}
            finally:
                s.close()
        except Exception:  # noqa: BLE001
            # при сбое БД не ломаем все страницы
            return {'announcements': []}

    return app
