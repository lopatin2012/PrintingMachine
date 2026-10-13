# test_zpl_pil_renderer.py
"""Тесты локального рендера ZPL → PNG (services/zpl_pil_renderer.py).

Локальный аналог Labelary: рендер без внешних сервисов и бинарников.
Проверяем, что рендер выдаёт PNG, корректно кодирует Code128/GS1-128
(сверка с python-barcode) и не падает на разных командах ZPL.
"""

import asyncio
import io

import pytest
from PIL import Image

from helpers.printers import substitute_placeholders
from services.zpl_pil_renderer import (
    _code128_bars,
    _decode_hex_field,
    _hri_text,
    render_zpl_to_png,
)
from services.zpl_renderer import ZPLRenderError, render_zpl_preview


def _png_size(png: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(png)).size


def _black_ratio(png: bytes, box: tuple[int, int, int, int]) -> float:
    img = Image.open(io.BytesIO(png)).convert('L')
    px = img.load()
    x0, y0, x1, y1 = box
    black = total = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            total += 1
            if px[x, y] < 128:
                black += 1
    return black / total if total else 0.0


def test_render_returns_png():
    png = render_zpl_to_png('^XA^PW400^LL200^FO10,10^A0N,40,40^FDHello^FS^XZ')
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    assert len(png) > 100


def test_render_full_substituted_label_has_content():
    zpl = (
        '^XA\n^PW812\n^LL1219\n'
        '^FO20,90\n^BCN,150,Y,N,N,N\n'
        '^FD{gs1_128_marking_date}{gs1_128_expiry_date}{gs1_gs}'
        '{gs1_128_batch}{gs1_gs}{gs1_128_current_box}{gs1_gs}{gs1_gtin}^FS\n'
        '^FO20,340\n^BXN,2,200\n'
        '^FD{uip_gtin}{uip_marking_date}{uip_article}{uip_batch}^FS\n'
        '^XZ'
    )
    preview = substitute_placeholders(
        zpl,
        batch_number='1564',
        marking_date=__import__('datetime').date(2026, 3, 5),
        expiration_date=__import__('datetime').date(2026, 4, 12),
        current_box=17,
        gtin='04601234567890',
        gtin_unit='04601234567890',
        article='123456',
        uip_include_batch=False,
    )
    png = render_zpl_to_png(preview)
    assert png[:8] == b'\x89PNG\r\n\x1a\n'

    # Область Code128 (y=90..240 dots, масштаб 2) — штрихи есть.
    assert _black_ratio(png, (40, 180, 1400, 480)) > 0.05
    # Область DataMatrix (y=340..540 dots) — модули есть.
    assert _black_ratio(png, (40, 680, 900, 1000)) > 0.02


def test_code128_bars_match_python_barcode():
    from barcode.codex import Code128, Gs1_128

    for data in ['123456789', 'ABC-123', '4601234567890']:
        assert _code128_bars(data, gs1=False) == Code128(data).build()[0]

    for data in ['0101234567890128', '0101234567890128\x1d2112345678', '01564']:
        gs1_data = data.replace('\x1d', '\xf1')
        assert _code128_bars(data, gs1=True) == Gs1_128(gs1_data).build()[0]


def test_hri_text_formats_gs1_ai():
    assert _hri_text('0101234567890128\x1d2112345678', gs1=True) == \
        '(01)01234567890128 (21)12345678'
    assert _hri_text('ABC', gs1=False) == 'ABC'


def test_hex_field_decode():
    assert _decode_hex_field('_48_65_6C_6C_6F') == 'Hello'


def test_render_rotated_barcode_and_boxes():
    zpl = (
        '^XA^PW400^LL400'
        '^FO10,10^GB380,380,4^FS'
        '^FO300,20^BCO,100,Y^FD123456^FS'
        '^XZ'
    )
    png = render_zpl_to_png(zpl)
    assert png[:8] == b'\x89PNG\r\n\x1a\n'


def test_render_inverted_label():
    png = render_zpl_to_png(
        '^XA^PW400^LL200^POI^FO10,10^A0N,40^FDINV^FS^XZ'
    )
    assert png[:8] == b'\x89PNG\r\n\x1a\n'


def test_unsupported_commands_are_ignored():
    zpl = (
        '^XA^PW400^LL200'
        '^FX комментарий^FS'
        '^PQ5^FS'
        '^FO10,10^A0N,40^FDok^FS'
        '^ZZ123^FS'
        '^XZ'
    )
    png = render_zpl_to_png(zpl)
    assert png[:8] == b'\x89PNG\r\n\x1a\n'


def test_render_local_falls_back_to_pil(monkeypatch):
    """render_zpl_preview при сломанном zebrash должен рендерить через PIL."""

    def broken_zebrash(*args, **kwargs):
        raise ZPLRenderError('zebrash недоступен (Go-архив вместо бинарника)')

    monkeypatch.setattr(
        'services.zpl_renderer.render_zpl_with_zebrash', broken_zebrash
    )
    monkeypatch.setattr('services.zpl_renderer.render_zpl_graphic_only',
                        lambda code: None)

    png = asyncio.run(render_zpl_preview(
        '^XA^PW400^LL200^FO10,10^A0N,40^FDHello^FS^XZ',
        params={}, use_zebrash=True,
    ))
    assert png[:8] == b'\x89PNG\r\n\x1a\n'


def test_datamatrix_renders_modules_or_placeholder():
    png = render_zpl_to_png(
        '^XA^PW400^LL200^FO10,10^BXN,2,150^FDABC123^FS^XZ'
    )
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    # В области DataMatrix (FO10,10, размер ~150 dots) есть чёрные пиксели.
    assert _black_ratio(png, (20, 20, 400, 200)) > 0.01


if __name__ == '__main__':
    pytest.main([__file__, '-v'])