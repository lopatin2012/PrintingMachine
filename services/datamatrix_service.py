# services/datamatrix_service.py
"""Клиент внешнего сервиса кодов DataMatrix.

Используется, когда у шаблона печати включён флаг `is_print_gtin_unit`:
перед печатью запрашивается список кодов DataMatrix для партии; если сервис
вернул коды — они подставляются в ZPL-шаблон в плейсхолдер `{datamatrix}`,
иначе печать отменяется с сообщением об ошибке.

Настройка (переменные окружения):
  DATAMATRIX_SERVICE_URL      — адрес внешнего сервиса (обязателен для работы
                                функции); на него отправляется POST с JSON;
  DATAMATRIX_SERVICE_TOKEN    — необязательный Bearer-токен для авторизации;
  DATAMATRIX_SERVICE_TIMEOUT  — таймаут запроса, секунд (по умолчанию 10).

Формат запроса (POST, application/json):
  {
    "product_article": "...",   // артикул продукта
    "gtin_unit": "...",         // GTIN единицы продукции
    "batch_number": "...",      // номер партии
    "marking_date": "YYYY-MM-DD",
    "first_box": 1,
    "last_box": 50,
    "count": 50                 // сколько кодов нужно
  }

Формат ответа: JSON-объект с ключом `codes` (список строк) либо просто
JSON-список строк.
"""
import logging
import os
from typing import List

import httpx

logger = logging.getLogger(__name__)

DATAMATRIX_SERVICE_URL = os.getenv('DATAMATRIX_SERVICE_URL', '').strip().rstrip('/')
DATAMATRIX_SERVICE_TOKEN = os.getenv('DATAMATRIX_SERVICE_TOKEN', '').strip()
DATAMATRIX_SERVICE_TIMEOUT = float(os.getenv('DATAMATRIX_SERVICE_TIMEOUT', '10'))


class DatamatrixServiceError(Exception):
    """Ошибка обращения к внешнему сервису DataMatrix."""
    pass


def _extract_codes(data) -> List[str]:
    """Извлечь список кодов из ответа сервиса (объект {codes: [...]} или список)."""
    if isinstance(data, list):
        return [str(item) for item in data if item not in (None, '')]
    if isinstance(data, dict):
        for key in ('codes', 'datamatrix', 'data', 'items'):
            value = data.get(key)
            if isinstance(value, list):
                return [str(item) for item in value if item not in (None, '')]
    return []


async def fetch_datamatrix_codes(
    *,
    product_article: str,
    gtin_unit: str,
    batch_number: str,
    marking_date,
    first_box: int,
    last_box: int,
    boxes_count: int,
) -> List[str]:
    """Запросить список кодов DataMatrix у внешнего сервиса.

    Возвращает список кодов. При недоступности/ошибке сервиса или пустом
    ответе поднимает DatamatrixServiceError с понятным сообщением.
    """
    if not DATAMATRIX_SERVICE_URL:
        raise DatamatrixServiceError(
            'Внешний сервис DataMatrix не настроен: укажите переменную '
            'DATAMATRIX_SERVICE_URL'
        )

    date_str = marking_date.isoformat() if hasattr(marking_date, 'isoformat') else str(marking_date)
    payload = {
        'product_article': product_article,
        'gtin_unit': gtin_unit,
        'batch_number': batch_number,
        'marking_date': date_str,
        'first_box': first_box,
        'last_box': last_box,
        'count': boxes_count,
    }
    headers = {'Content-Type': 'application/json'}
    if DATAMATRIX_SERVICE_TOKEN:
        headers['Authorization'] = f'Bearer {DATAMATRIX_SERVICE_TOKEN}'

    logger.info(
        'Запрос кодов DataMatrix: %s (партия %s, коробки %d–%d, %d шт.)',
        DATAMATRIX_SERVICE_URL, batch_number, first_box, last_box, boxes_count,
    )

    try:
        async with httpx.AsyncClient(timeout=DATAMATRIX_SERVICE_TIMEOUT) as client:
            response = await client.post(
                DATAMATRIX_SERVICE_URL, json=payload, headers=headers,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.RequestError as e:
        raise DatamatrixServiceError(
            f'Не удалось связаться с сервисом DataMatrix: {e}'
        ) from e
    except (httpx.HTTPStatusError, ValueError) as e:
        raise DatamatrixServiceError(
            f'Сервис DataMatrix вернул ошибку: {e}'
        ) from e

    codes = _extract_codes(data)
    logger.info('Сервис DataMatrix вернул %d кодов', len(codes))
    return codes
