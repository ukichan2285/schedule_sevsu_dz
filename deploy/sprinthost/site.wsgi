"""WSGI-вход для SprintHost (uWSGI / mod_wsgi), Python 3.13.

Кладётся в корень сайта:
  /home/<login>/domains/<domain>/public_html/site.wsgi
Код проекта — вне веб-корня: /home/<login>/schedule_app
"""
import glob
import os
import sys

SITE_ROOT = os.path.dirname(os.path.abspath(__file__))                 # public_html
HOME = os.path.dirname(os.path.dirname(os.path.dirname(SITE_ROOT)))    # /home/<login>
APP_DIR = os.path.join(HOME, 'schedule_app')
VENV_DIR = os.path.join(HOME, 'python')

# Активируем виртуальное окружение аккаунта (~/python):
# virtualenv кладёт activate_this.py, venv — нет (тогда добавляем site-packages)
activate_this = os.path.join(VENV_DIR, 'bin', 'activate_this.py')
if os.path.exists(activate_this):
    with open(activate_this) as f:
        exec(f.read(), {'__file__': activate_this})
else:
    for sp in glob.glob(os.path.join(VENV_DIR, 'lib', 'python*', 'site-packages')):
        sys.path.insert(0, sp)

sys.path.insert(0, APP_DIR)

from app import create_app  # noqa: E402

application = create_app()

if __name__ == '__main__':
    application.run()
