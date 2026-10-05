#!/usr/bin/env python3
"""Запуск веб-сервера Flask"""

from app import create_app

app = create_app()

if __name__ == '__main__':
    print('🚀 Запуск веб-сервера...')
    print('🌐 Адрес: http://127.0.0.1:5000')
    print('📚 Расписание доступно по адресу выше')
    print('⚠️  Для публикации используйте: flask run --host=0.0.0.0 --port=80')
    app.run(debug=True, host='127.0.0.1', port=5000)
