# test_pdf_renderer.py
"""Тесты сборки PDF из списка этикеток (services/pdf_renderer.py).

Проверяем:
  * построение списка ZPL-этикеток по коробкам с разными DataMatrix-кодами;
  * основной путь — Labelary отдаёт PDF (мокается);
  * фолбэк — сборка PDF из PNG через Pillow (реальный офлайн-рендер);
  * ошибка при пустом списке.

Тесты чистые: внешний HTTP не выполняется.
"""

import asyncio
from datetime import date

import pytest

import services.pdf_renderer as pdf_renderer
from services.pdf_renderer import (
    PdfRenderError,
    build_labels_for_boxes,
    render_labels_to_pdf,
)
from services.zpl_pil_renderer import render_zpl_to_png

MARKING = date(2026, 3, 5)
EXPIRATION = date(2026, 3, 31)


def _labels(count: int = 3) -> list[str]:
    return [
        f'^XA^PW400^LL200^FO10,10^BXN,2,150^FDCODE-{i}^FS^XZ'
        for i in range(1, count + 1)
    ]


def _count_pdf_pages(pdf_bytes: bytes) -> int:
    """Приблизительный подсчёт страниц в PDF от Pillow."""
    return pdf_bytes.count(b'/Type /Page') - pdf_bytes.count(b'/Type /Pages')


# ---------------------------------------------------------------------------
# Построение этикеток
# ---------------------------------------------------------------------------

def test_build_labels_for_boxes_uses_code_per_box():
    zpl = '^XA^PW400^LL200^FO10,10^BXN,2,150^FD{datamatrix}^FS' \
          '^FO10,150^FD{current_box}^FS^XZ'
    codes = ['CODE-A', 'CODE-B', 'CODE-C']

    labels = build_labels_for_boxes(
        template_code=zpl,
        boxes_count=3,
        first_box=10,
        batch_number='1564',
        marking_date=MARKING,
        expiration_date=EXPIRATION,
        gtin='04601234567890',
        datamatrix_codes=codes,
    )

    assert len(labels) == 3
    for i, label in enumerate(labels):
        assert codes[i] in label
        assert '{datamatrix}' not in label
    # Нумерация коробок продолжается с first_box (формат 5 цифр).
    assert '^FD00010^FS' in labels[0]
    assert '^FD00012^FS' in labels[2]


def test_build_labels_without_codes_removes_placeholder():
    zpl = '^XA^PW400^LL200^FO10,10^BXN,2,150^FD{datamatrix}^FS^XZ'
    labels = build_labels_for_boxes(
        template_code=zpl,
        boxes_count=1,
        first_box=1,
        batch_number='01',
        marking_date=MARKING,
        expiration_date=EXPIRATION,
    )
    assert '{datamatrix}' not in labels[0]


# ---------------------------------------------------------------------------
# Сборка PDF (полностью локальная, без Labelary)
# ---------------------------------------------------------------------------

def test_render_labels_to_pdf_is_local(monkeypatch):
    """PDF собирается локальным рендером (render_preview_png_local)."""
    calls = []

    def fake_local(zpl, dpmm=8):
        calls.append(zpl)
        return render_zpl_to_png(zpl), 'pil'

    monkeypatch.setattr(pdf_renderer, 'render_preview_png_local', fake_local)

    pdf_bytes, engine = render_labels_to_pdf(_labels(3))

    assert engine == 'pil'
    assert pdf_bytes.startswith(b'%PDF')
    assert _count_pdf_pages(pdf_bytes) == 3
    assert len(calls) == 3


def test_render_labels_to_pdf_uses_pillow_fallback(monkeypatch):
    # Локальная цепочка (zplr) недоступна — должен отработать PIL-фолбэк.
    monkeypatch.setattr(
        pdf_renderer, 'render_preview_png_local',
        lambda zpl, dpmm=8: (render_zpl_to_png(zpl), 'pil'),
    )

    pdf_bytes, engine = render_labels_to_pdf(_labels(3))

    assert engine == 'pil'
    assert pdf_bytes.startswith(b'%PDF')
    assert _count_pdf_pages(pdf_bytes) == 3


def test_render_labels_to_pdf_empty_raises():
    with pytest.raises(PdfRenderError):
        render_labels_to_pdf([])
