#!/usr/bin/env python3
"""Скрипт для обновления расписания с сайта SEVSU"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.parser import ScheduleParser
from app.models import Session, Schedule, init_db

def update_schedule(group_name='rs-s-26-1-o', day_filter=None):
    """Обновить расписание для указанной группы"""
    print('=== Обновление расписания ===')
    print(f'Группа: {group_name}')
    if day_filter:
        print(f'День: {day_filter}')
    print()
    
    # Инициализация БД
    init_db()
    session = Session()
    
    try:
        # Создаем парсер
        parser = ScheduleParser()
        
        # Загружаем страницу
        url = f'https://schedule.sevsu.ru/groups/{group_name}'
        print(f'Загрузка: {url}')
        
        html = parser.fetch_page(url)
        if not html:
            print('❌ Ошибка загрузки страницы')
            print('Причина: DDoS-Guard защита требует российский IP-адрес')
            return False
        
        # Проверяем на DDoS-Guard
        if 'DDoS-Guard' in html or 'cdn-cgi' in html:
            print('⚠️ Обнаружен DDoS-Guard защита')
            print('Парсинг возможен только с российского IP-адреса')
            return False
        
        # Парсим расписание
        lessons = parser.parse_schedule(html, day_filter)
        
        if not lessons:
            print('❌ Расписание пустое')
            return False
        
        print(f'✅ Найдено {len(lessons)} занятий')
        print()
        
        # Сохраняем в базу
        saved_count = 0
        updated_count = 0
        
        for lesson_data in lessons:
            # Проверяем, есть ли уже такое занятие
            existing = session.query(Schedule).filter(
                Schedule.day_of_week == lesson_data['day_of_week'],
                Schedule.lesson_number == lesson_data['lesson_number'],
                Schedule.subject == lesson_data['subject']
            ).first()
            
            if not existing:
                lesson = Schedule(
                    date=lesson_data['created_at'],
                    day_of_week=lesson_data['day_of_week'],
                    lesson_number=lesson_data['lesson_number'],
                    subject=lesson_data['subject'],
                    teacher=lesson_data['teacher'],
                    location=lesson_data['location'],
                    lesson_type=lesson_data['lesson_type'],
                    hash=lesson_data['hash'],
                    created_at=lesson_data['created_at'],
                    updated_at=lesson_data['updated_at']
                )
                session.add(lesson)
                saved_count += 1
            else:
                updated_count += 1
        
        session.commit()
        session.close()
        
        print(f'✅ Сохранено новых: {saved_count}')
        print(f'✅ Обновлено: {updated_count}')
        print()
        
        # Показываем примеры
        print('Примеры занятий:')
        for lesson in lessons[:3]:
            print(f'  - {lesson["day_of_week"]} п.{lesson["lesson_number"]}: {lesson["subject"]}')
            if lesson['teacher']:
                print(f'    {lesson["teacher"]}')
            if lesson['location']:
                print(f'    {lesson["location"]}')
        
        return True
        
    except Exception as e:
        print(f'❌ Ошибка: {e}')
        if session:
            session.rollback()
            session.close()
        return False

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Обновление расписания SEVSU')
    parser.add_argument('--group', default='rs-s-26-1-o', help='Название группы')
    parser.add_argument('--day', choices=['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота'], 
                       help='Фильтр по дню недели')
    
    args = parser.parse_args()
    
    success = update_schedule(args.group, args.day)
    sys.exit(0 if success else 1)
