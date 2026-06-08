import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image
from zebrafy import ZebrafyZPL

from config import ZEBRASH_BINARY, ZPL_RENDER_DEFAULTS

logger = logging.getLogger(__name__)

class ZPLRenderError(Exception):
    """Исключение при ошибке рендеринга ZPL"""
    pass

def render_zpl_with_zebrash(
        zpl_code: str,
        width_mm: float = None,
        height_mm: float = None,
        dpmm: int = None,
        timeout: int = None
) -> bytes:
    """
    Рендеринг ZPL-кода в PNG через бинарник zebrash.
    :param zpl_code:
    :param width_mm:
    :param height_mm:
    :param dpmm:
    :param timeout:
    :return:
    """

    width_mm = width_mm or ZPL_RENDER_DEFAULTS['width_mm']
    height_mm = height_mm or ZPL_RENDER_DEFAULTS['height_mm']
    dpmm = dpmm or ZPL_RENDER_DEFAULTS['dpmm']
    timeout = timeout or ZPL_RENDER_DEFAULTS['timeout_sec']

    if not Path(ZEBRASH_BINARY).exists():
        raise ZPLRenderError(f'Бинарник zebrash не найден: {ZEBRASH_BINARY}')

    with tempfile.NamedTemporaryFile(mode='w', suffix='.zpl', delete=False) as zpl_file:
        zpl_file.write(zpl_code)
        zpl_path = zpl_file.name

    try:
        cmd = [
            '--width', str(width_mm),
            '--height', str(height_mm),
            '--dpmm', str(dpmm),
            '--output', 'png', # Выводим в PNGб
            zpl_path
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=False
        )

        if result.returncode != 0:
            error_msg = result.stderr.decode('utf-8', errors='replace').strip()
            raise ZPLRenderError(f'zebrash вернул ошибку: {error_msg}')

        if not result.stdout:
            raise ZPLRenderError('zebrash вернул пустой результат')

        if not result.stdout.startswith(b'\x89PNG'):
            logger.warning(f'zebrash вернул данные, не являющиеся PNG. (bytes: [{result.stdout[:20]})')

        return result.stdout

    except subprocess.TimeoutExpired:
        raise ZPLRenderError(f"Таймаут рендеринга ZPL ({timeout}с)")
    except FileNotFoundError:
        raise ZPLRenderError(f"Не удалось запустить бинарник: {ZEBRASH_BINARY}")
    finally:
        # Удаляем временный файл
        Path(zpl_path).unlink(missing_ok=True)


def render_zpl_graphic_only(zpl_code: str) -> Optional[Image.Image]:
    """
    Рендер только графической команды ^GF через zebrafy.

    Returns:
        PIL.Image или None, если zebrafy не справился
    """
    try:
        zebrafy = ZebrafyZPL(zpl_code)
        images = zebrafy.to_images()
        if images:
            return images[0]  # Возвращаем первое изображение
    except Exception as e:
        logger.debug(f"zebrafy не смог обработать ZPL: {e}")
    return None


async def render_zpl_preview(
        zpl_code: str,
        params: dict = None,
        use_zebrash: bool = True
) -> bytes:
    """
    Асинхронный интерфейс для рендеринга превью.

    1. Подставляет параметры в шаблон (если нужно)
    2. Пытается использовать zebrafy для быстрых случаев
    3. Если не вышло — вызывает zebrash через subprocess

    Args:
        zpl_code: Исходный ZPL-код
        params: Словарь параметров для подстановки (batch, date, etc.)
        use_zebrash: Если False — только zebrafy, без вызова внешнего процесса

    Returns:
        bytes: PNG-изображение
    """
    # Шаг 1: Подстановка параметров в шаблон
    if params:
        zpl_code = _substitute_params(zpl_code, params)

    # Шаг 2: Пробуем быстрый рендер через zebrafy (только ^GF)
    if not use_zebrash:
        img = render_zpl_graphic_only(zpl_code)
        if img:
            from io import BytesIO
            buf = BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        raise ZPLRenderError("zebrafy не смог обработать шаблон, а use_zebrash=False")

    # Шаг 3: Полный рендер через zebrash
    try:
        return await asyncio.to_thread(
            render_zpl_with_zebrash,
            zpl_code=zpl_code,
            **(params or {})
        )
    except ZPLRenderError as e:
        logger.warning(f"Рендер через zebrash не удался: {e}")
        # Фолбэк: пробуем zebrafy
        img = render_zpl_graphic_only(zpl_code)
        if img:
            from io import BytesIO
            buf = BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        raise


def _substitute_params(zpl_code: str, params: dict) -> str:
    """
    Простая подстановка параметров в ZPL-код.

    Поддерживает плейсхолдеры вида:
    - {{batch_number}} → 01
    - {{marking_date}} → 240315
    - {{box_number}} → 1

    Для сложных случаев можно расширить логику или использовать Jinja2.
    """
    result = zpl_code

    # Пример: заменяем ^FD{{batch_number}}^FS на ^FD01^FS
    replacements = {
        '{{batch_number}}': params.get('batch_number', '01'),
        '{{marking_date}}': params.get('marking_date', ''),  # YYMMDD
        '{{box_number}}': str(params.get('current_box', 1)),
        '{{total_boxes}}': str(params.get('total_boxes', 1)),
    }

    for placeholder, value in replacements.items():
        result = result.replace(placeholder, str(value))

    return result