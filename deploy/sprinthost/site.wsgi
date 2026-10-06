"""WSGI-вход для SprintHost (uWSGI / mod_wsgi), Python 3.13.

Кладётся в корень сайта:
  /home/<login>/domains/<domain>/public_html/site.wsgi
Код проекта — вне веб-корня: /home/<login>/schedule_app
"""
import glob
import os
import sys
import traceback

SITE_ROOT = os.path.dirname(os.path.abspath(__file__))                 # public_html
HOME = os.path.dirname(os.path.dirname(os.path.dirname(SITE_ROOT)))    # /home/<login>
APP_DIR = os.path.join(HOME, 'schedule_app')
VENV_DIR = os.path.join(HOME, 'python')

# Виртуальное окружение аккаунта (~/python):
# virtualenv кладёт activate_this.py, venv — нет (тогда добавляем site-packages)
activate_this = os.path.join(VENV_DIR, 'bin', 'activate_this.py')
if os.path.exists(activate_this):
    with open(activate_this) as f:
        exec(f.read(), {'__file__': activate_this})
else:
    for sp in glob.glob(os.path.join(VENV_DIR, 'lib', 'python*', 'site-packages')):
        sys.path.insert(0, sp)

# Сбрасываем кэш модулей app, чтобы перечитать .env при перезапуске скрипта
for _name in [n for n in sys.modules if n == 'app' or n.startswith('app.')]:
    del sys.modules[_name]

sys.path.insert(0, APP_DIR)


class _NoScriptName:
    """mod_wsgi выставляет SCRIPT_NAME=/site.wsgi — убираем префикс,
    чтобы url_for/редиректы были от корня сайта."""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        environ['SCRIPT_NAME'] = ''
        return self.app(environ, start_response)


_LOG = os.path.join(APP_DIR, 'wsgi.log')
try:
    from app import create_app  # noqa: E402

    application = _NoScriptName(create_app())
    with open(_LOG, 'a') as _f:
        _f.write('OK db=%s\n' % (os.environ.get('DATABASE_URL', '')))
except Exception:  # noqa: BLE001
    with open(_LOG, 'a') as _f:
        _f.write('===== ERROR =====\n')
        traceback.print_exc(file=_f)
    raise

if __name__ == '__main__':
    application.run()
