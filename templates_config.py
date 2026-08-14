# templates_config.py

from datetime import datetime
from urllib.parse import urlencode

from fastapi.templating import Jinja2Templates
from helper import BASE_DIR

templates = Jinja2Templates(directory=BASE_DIR / 'templates')

# Форматирование даты.
def format_datetime(value: datetime, format: str = '%d.%m.%Y %H:%M'):
    return value.strftime(format) if value else ''

def printer_type_label(value) -> str:
    """Название типа принтера для отображения: zebra → Zebra, tsc → TSC."""
    return {'zebra': 'Zebra', 'tsc': 'TSC'}.get((value or '').strip().lower(), value or '—')

def build_pagination_url(page: int, params: dict = None, endpoint: str = 'products') -> str:
    """Генерация ссылок пагинации"""
    query_params = params.copy() if page else {}
    query_params['page'] = page
    query_string = urlencode({k: v for k, v in query_params.items() if v is not None})
    return f'/{endpoint}?{query_string}' if query_string else f'/{endpoint}'

templates.env.filters['format_datetime'] = format_datetime
templates.env.filters['printer_type_label'] = printer_type_label
templates.env.globals['build_pagination_url'] = build_pagination_url

__all__ = ['templates']
