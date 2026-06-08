# helper.py

from pathlib import Path

# Определяем корень проекта.
BASE_DIR = Path(__file__).parent

# Глобальное определение кириллических символов
CYRILLIC_CHARS = set('АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя')