# services/pdf_renderer.py
"""Сборка списка ZPL-этикеток в один многостраничный PDF.

Используется, когда пользователь вместо принтера выбирает «Сохранить в PDF»:
этикетки (по одной на коробку, с подставленными DataMatrix-кодами) рендерятся
в PDF, который сразу скачивается.

Генерация полностью локальная — без внешних сервисов: каждая этикетка
рендерится в PNG цепочкой `services/preview_renderer.py` (zplr → PIL; DataMatrix
рисует собственный движок `services/datamatrix_renderer.py`), затем страницы
собираются в PDF через Pillow.
"""

from __future__ import annotations

import io
import logging

from helpers.printers import substitute_placeholders
from services.preview_renderer import render_preview_png_local

logger = logging.getLogger(__name__)

# Разрешение PDF: 8 точек/мм = 203 dpi (стандарт Zebra).
PDF_DPI = 203


class PdfRenderError(Exception):
    """Ошибка генерации PDF (локальный рендер недоступен)."""


def build_labels_for_boxes(
    *,
    template_code: str,
    boxes_count: int,
    first_box: int,
    batch_number: str,
    marking_date,
    expiration_date,
    gtin: str = '',
    gtin_unit: str = '',
    article: str = '',
    uip_include_batch: bool = False,
    product_name: str = '',
    name_line1: str = '',
    name_line2: str = '',
    tu_number: str = '',
    weight: str = '',
    fat_content: str = '',
    units_count: str = '',
    datamatrix_codes: list | None = None,
) -> list[str]:
    """Собрать готовые ZPL-этикетки (по одной на коробку) для PDF.

    Логика подстановки та же, что при реальной печати, но без конвертации
    кириллицы в HEX (PDF-рендер, как и предпросмотр, работает с UTF-8).
    На каждую коробку берётся свой DataMatrix-код из `datamatrix_codes`.
    """
    codes = datamatrix_codes or []
    labels: list[str] = []
    for i in range(boxes_count):
        labels.append(
            substitute_placeholders(
                template_code,
                batch_number=batch_number,
                marking_date=marking_date,
                expiration_date=expiration_date,
                current_box=first_box + i,
                gtin=gtin,
                gtin_unit=gtin_unit,
                article=article,
                uip_include_batch=uip_include_batch,
                datamatrix=(codes[i] if i < len(codes) else ''),
                product_name=product_name,
                name_line1=name_line1,
                name_line2=name_line2,
                tu_number=tu_number,
                weight=weight,
                fat_content=fat_content,
                units_count=units_count,
            )
        )
    return labels


def _render_labels_via_png(labels: list[str], dpmm: int) -> tuple[bytes, str]:
    """Отрендерить каждую этикетку в PNG и собрать страницы PDF (Pillow)."""
    from PIL import Image

    pages = []
    engine = 'pil'
    for label in labels:
        png_bytes, page_engine = render_preview_png_local(label, dpmm)
        engine = page_engine
        pages.append(Image.open(io.BytesIO(png_bytes)).convert('RGB'))
        logger.debug("PDF-страница отрендерена движком %s", page_engine)

    if not pages:
        raise PdfRenderError("Нет этикеток для PDF")

    buffer = io.BytesIO()
    pages[0].save(
        buffer,
        format="PDF",
        save_all=True,
        append_images=pages[1:],
        resolution=PDF_DPI,
    )
    return buffer.getvalue(), engine


def render_labels_to_pdf(labels: list[str], dpmm: int = 8) -> tuple[bytes, str]:
    """Собрать PDF из списка ZPL-этикеток. Возвращает (pdf_bytes, engine)."""
    if not labels:
        raise PdfRenderError("Нет этикеток для PDF")

    try:
        return _render_labels_via_png(labels, dpmm)
    except Exception as e:  # noqa: BLE001
        raise PdfRenderError(f"Не удалось собрать PDF локально: {e}") from e

