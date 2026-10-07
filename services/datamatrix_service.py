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
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

DATAMATRIX_SERVICE_URL = os.getenv('DATAMATRIX_SERVICE_URL', '').strip().rstrip('/')
DATAMATRIX_SERVICE_TOKEN = os.getenv('DATAMATRIX_SERVICE_TOKEN', '').strip()
DATAMATRIX_SERVICE_TIMEOUT = float(os.getenv('DATAMATRIX_SERVICE_TIMEOUT', '10'))

# Базовый адрес сервиса кодов по UUID продукта (СУЗ/СУП).
# По умолчанию — локальный сервис маркировки.
CODES_SERVICE_URL = os.getenv('CODES_SERVICE_URL', 'http://127.0.0.1:8000').strip().rstrip('/')
CODES_SERVICE_TOKEN = os.getenv('CODES_SERVICE_TOKEN', DATAMATRIX_SERVICE_TOKEN).strip()
CODES_SERVICE_TIMEOUT = float(os.getenv('CODES_SERVICE_TIMEOUT', '10'))

# Путь метода выдачи кодов по UUID продукта.
CODES_BY_UUID_PATH = '/codes/api/get_codes_for_printer_by_product_uuid/'


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


async def fetch_datamatrix_codes_by_uuid(
    *,
    external_uuid: str,
    amount_codes: int,
    issued: bool = False,
    timeout: Optional[float] = None,
) -> List[str]:
    """Запросить коды DataMatrix у внешнего сервиса по UUID продукта.

    Обращается к GET-методу ``/codes/api/get_codes_for_printer_by_product_uuid/``
    (``uuid_product``, ``amount_codes``, при необходимости ``issued=1``).

    ``timeout`` — таймаут запроса в секундах; если не задан, используется
    ``CODES_SERVICE_TIMEOUT``. Для больших партий (выгрузка TXT на тысячи
    кодов) можно передать увеличенный таймаут.

    Возвращает список кодов (может быть пустым, если свободных кодов нет).
    При недоступности сервиса, некорректном ответе или ошибке на стороне
    сервиса (``is_error``) поднимает :class:`DatamatrixServiceError`.
    """
    external_uuid = (external_uuid or '').strip()
    if not external_uuid:
        raise DatamatrixServiceError(
            'Не задан UUID продукта во внешнем сервисе — невозможно '
            'запросить коды DataMatrix'
        )
    if amount_codes <= 0:
        return []

    url = CODES_SERVICE_URL + CODES_BY_UUID_PATH
    params = {'uuid_product': external_uuid, 'amount_codes': int(amount_codes)}
    if issued:
        params['issued'] = '1'

    headers = {'Accept': 'application/json'}
    if CODES_SERVICE_TOKEN:
        headers['Authorization'] = f'Bearer {CODES_SERVICE_TOKEN}'

    logger.info(
        'Запрос %d кодов DataMatrix по UUID %s: %s',
        amount_codes, external_uuid, url,
    )

    effective_timeout = CODES_SERVICE_TIMEOUT if timeout is None else timeout
    try:
        async with httpx.AsyncClient(timeout=effective_timeout) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.RequestError as e:
        raise DatamatrixServiceError(
            f'Не удалось связаться с сервисом кодов по UUID: {e}'
        ) from e

    if response.status_code >= 400:
        # Сервис отдаёт понятное сообщение в JSON (например, для 404).
        message = None
        try:
            body = response.json()
            if isinstance(body, dict):
                message = body.get('message')
        except ValueError:
            message = None
        if response.status_code == 404 and not message:
            message = f'Продукт с UUID {external_uuid} не найден во внешнем сервисе'
        raise DatamatrixServiceError(
            message or f'Сервис кодов вернул HTTP {response.status_code}'
        )

    try:
        data = response.json()
    except ValueError as e:
        raise DatamatrixServiceError(
            f'Сервис кодов по UUID вернул некорректный ответ: {e}'
        ) from e

    if isinstance(data, dict) and data.get('is_error'):
        raise DatamatrixServiceError(
            data.get('message') or 'Сервис кодов вернул ошибку'
        )

    codes = _extract_codes(data)
    logger.info(
        'Сервис кодов по UUID %s вернул %d кодов', external_uuid, len(codes),
    )
    return codes
