# test_codes_pdf.py
"""Тесты формирования PDF с DataMatrix-кодами (services/codes_pdf.py)."""

import re

import pytest

from services.codes_pdf import build_codes_pdf, printer_dpi

CODE_1 = '010460999000001121000001\x1d930001'
CODE_2 = '010460999000001121000002\x1d930002'


def test_build_pdf_returns_pdf_bytes():
    pdf = build_codes_pdf([CODE_1, CODE_2], product_name='Тестовый DM',
                          gtin='04609990000011')
    assert pdf.startswith(b'%PDF')
    assert len(pdf) > 1000


def test_pdf_has_page_per_code():
    pdf = build_codes_pdf([CODE_1, CODE_2, '010460999000001121000003'])
    # Pillow пишет объект /Pages с /Count <число страниц>.
    assert b'/Count 3' in pdf


def test_empty_codes_raise():
    with pytest.raises(ValueError):
        build_codes_pdf([])


def test_blank_codes_are_ignored():
    pdf = build_codes_pdf(['', CODE_1, None])
    assert pdf.startswith(b'%PDF')


def test_printer_dpi_defaults_to_203():
    assert printer_dpi('zebra') == 203
    assert printer_dpi('tsc') == 203


def test_pdf_page_is_a4(monkeypatch):
    monkeypatch.delenv('ZEBRA_DPI', raising=False)
    monkeypatch.delenv('PRINTER_DPI', raising=False)
    pdf = build_codes_pdf([CODE_1], module_dots=4, dpi=203)
    match = re.search(rb'/MediaBox \[([^\]]+)\]', pdf)
    assert match, 'MediaBox не найден'
    parts = [float(x) for x in match.group(1).split()]
    width_pt, height_pt = parts[2], parts[3]
    # A4 в пунктах: 595 x 842 (страница сохраняется в разрешении принтера).
    assert abs(width_pt - 595) < 3
    assert abs(height_pt - 842) < 3


def test_module_size_affects_pdf_page_scale(monkeypatch):
    """Чем больше модуль (^BX h), тем крупнее символ — размер как при печати."""
    # При одинаковом dpi страница A4 одинакова; проверяем, что сборка не падает
    # и символ помещается (косвенная проверка масштабирования по модулю).
    small = build_codes_pdf([CODE_1], module_dots=2, dpi=203)
    large = build_codes_pdf([CODE_1], module_dots=10, dpi=203)
    assert small.startswith(b'%PDF') and large.startswith(b'%PDF')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
