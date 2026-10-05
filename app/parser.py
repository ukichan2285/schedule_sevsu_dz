import requests
from bs4 import BeautifulSoup
from datetime import datetime
import hashlib
import re

class ScheduleParser:
    def __init__(self):
        self.base_url = 'https://schedule.sevsu.ru'
        self.session = requests.Session()
        # Отключаем использование системных прокси/VPN (trust_env)
        self.session.trust_env = False
        self.session.proxies = {'http': None, 'https': None}
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'ru-RU,ru;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
    
    def fetch_page(self, url):
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f'Ошибка fetch_page: {e}')
            return None
    
    def parse_schedule(self, html, day_filter=None):
        if not html:
            return []
        soup = BeautifulSoup(html, 'html.parser')
        items = []
        
        rows = soup.find_all(['tr'])
        current_day = None
        
        day_names = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота']
        
        for row in rows:
            cells = row.find_all(['td', 'th'])
            if not cells:
                continue
            
            row_text = ' '.join([c.get_text(strip=True) for c in cells])
            for day in day_names:
                if day in row_text:
                    current_day = day
                    break
            
            if not current_day:
                continue
            
            if day_filter and current_day != day_filter:
                continue
            
            if len(cells) >= 3:
                lesson_data = self._extract_lesson(cells, current_day)
                if lesson_data:
                    items.append(lesson_data)
        
        return items
    
    def _extract_lesson(self, cells, day_of_week):
        try:
            texts = [c.get_text(strip=True) for c in cells]
            lesson_number = None
            for t in texts:
                m = re.match(r'^(\d+)[.) ]', t)
                if m:
                    lesson_number = int(m.group(1))
                    break
            
            if not lesson_number:
                return None
            
            subject = ''
            teacher = ''
            location = ''
            
            for t in texts:
                if 'лект' in t.lower() or 'прак' in t.lower() or 'сем' in t.lower():
                    if not subject:
                        subject = t
                elif 'каб' in t.lower() or 'ауд' in t.lower():
                    location = t
                elif any(name in t for name in ['Иванов', 'Петров', 'Сидоров', 'Смирнов']):
                    teacher = t
            
            if not subject and len(texts) > 1:
                subject = texts[1]
            if not teacher and len(texts) > 2:
                teacher = texts[2]
            if not location and len(texts) > 3:
                location = texts[3]
            
            lesson_type = ''
            for t in texts:
                if 'лек' in t.lower():
                    lesson_type = 'лекция'
                elif 'прак' in t.lower():
                    lesson_type = 'практика'
                elif 'сем' in t.lower():
                    lesson_type = 'семинар'
            
            hash_str = f'{day_of_week}|{lesson_number}|{subject}|{teacher}|{location}|{lesson_type}'
            item_hash = hashlib.md5(hash_str.encode()).hexdigest()
            
            return {
                'day_of_week': day_of_week,
                'lesson_number': lesson_number,
                'subject': subject,
                'teacher': teacher,
                'location': location,
                'lesson_type': lesson_type,
                'hash': item_hash,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            }
        except Exception as e:
            print(f'Ошибка _extract_lesson: {e}')
            return None
    
    def get_schedule_for_group(self, group_name='rs-s-26-1-o', day_filter=None):
        url = f'{self.base_url}/groups/{group_name}'
        html = self.fetch_page(url)
        if html:
            return self.parse_schedule(html, day_filter)
        return []
