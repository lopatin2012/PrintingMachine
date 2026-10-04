# services/codes_pdf.py
"""Формирование PDF с DataMatrix-кодами.

На каждой странице — ТОЛЬКО изображение DataMatrix (собственный рендерер
``services.datamatrix_renderer``), без текста. Размер символа совпадает с
печатью на принтере: страница A4 отдаётся при разрешении принтера, а модуль
DataMatrix берётся из ``^BX h`` шаблона, поэтому физический размер кода в PDF
равен размеру при печати (например, 4 точки при 203 dpi ≈ 0.5 мм на модуль).
"""

from __future__ import annotations

import io
import logging
import os
from typing import List

from PIL import Image

logger = logging.getLogger(__name__)

# Размер A4 в дюймах.
A4_WIDTH_IN = 8.2677
A4_HEIGHT_IN = 11.6929

# Тихая зона DataMatrix (в модулях) — белое поле вокруг символа.
DM_QUIET_ZONE = 2

# Разрешение принтера по умолчанию (точек на дюйм), как при печати.
DEFAULT_PRINTER_DPI = 203


def printer_dpi(printer_type: str = 'zebra') -> int:
    """Разрешение принтера (dpi) по его типу.

    Zebra и TSC по умолчанию 203 dpi (8 точек/мм); можно переопределить
    переменными окружения ``ZEBRA_DPI`` / ``TSC_DPI`` (или общим
    ``PRINTER_DPI``).
    """
    if (printer_type or '').strip().lower() == 'tsc':
        env_name = 'TSC_DPI'
    else:
        env_name = 'ZEBRA_DPI'
    try:
        return int(os.getenv(env_name, os.getenv('PRINTER_DPI', str(DEFAULT_PRINTER_DPI))))
    except (TypeError, ValueError):
        return DEFAULT_PRINTER_DPI


def _render_page(code: str, module_dots: int, dpi: int) -> Image.Image:
    """Страница PDF: только DataMatrix, с размером модуля как при печати."""
    from services.datamatrix_renderer import render_datamatrix_image

    page_w = round(A4_WIDTH_IN * dpi)
    page_h = round(A4_HEIGHT_IN * dpi)
    page = Image.new('RGB', (page_w, page_h), 'white')

    try:
        dm_img = render_datamatrix_image(
            code, module_px=max(1, int(module_dots)), quiet_zone=DM_QUIET_ZONE,
        )
    except Exception as e:  # noqa: BLE001 - не роняем весь PDF из-за одного кода
        logger.warning('DataMatrix не отрисован для PDF (%s): %s', code[:20], e)
        return page

    page.paste(
        dm_img,
        ((page_w - dm_img.width) // 2, (page_h - dm_img.height) // 2),
    )
    return page


def build_codes_pdf(
    codes: List[str],
    *,
    module_dots: int = 4,
    dpi: int = DEFAULT_PRINTER_DPI,
    product_name: str = '',
    gtin: str = '',
) -> bytes:
    """Собрать PDF со всеми DataMatrix-кодами (страница на код).

    ``module_dots`` — размер модуля из шаблона (``^BX h``), ``dpi`` — разрешение
    принтера: вместе они задают физический размер символа, как при печати на
    Zebra. Параметры ``product_name``/``gtin`` принимаются для совместимости и
    не используются. Возвращает bytes PDF; ``ValueError``, если кодов нет.
    """
    codes = [c for c in (codes or []) if c]
    if not codes:
        raise ValueError('Нет кодов для формирования PDF')

    dpi = max(1, int(dpi))
    module_dots = max(1, int(module_dots))
    pages = [_render_page(code, module_dots, dpi) for code in codes]

    buf = io.BytesIO()
    first, rest = pages[0], pages[1:]
    first.save(
        buf, format='PDF', save_all=True, append_images=rest, resolution=float(dpi),
    )
    return buf.getvalue()
