# test_print_queue_datamatrix.py
"""Тесты растровой печати DataMatrix (services/print_queue.py).

Печать DataMatrix-шаблонов больше не отдаёт ``^BX`` на кодирование самому
принтеру (у Zebra редкие поля кодировались пустыми — на стикере без другого
содержимого получался полностью пустой стикер). Вместо этого поле ``^BX``
заменяется растром ``^GF`` нашим рендерером (как в превью).

Проверяем: подмена происходит для реального шаблона, получившийся ``^GFA``
читается обратно в исходный код (в т.ч. с ``_`` и GS-разделителем), а ZPL без
DataMatrix не меняется. Всё локально, без сети и принтера.
"""

import io
import re

from PIL import Image
from pylibdmtx.pylibdmtx import decode as dmtx_decode

from helpers.printers import substitute_placeholders
from services.print_queue import rasterize_datamatrix
from datetime import date

# Реальный шаблон из БД («Печать DM»): ^FO с пробелом и «странным» \, перед ^FD.
TEMPLATE = (
    '^XA^PW1100\r\n^LL200\r\n^CI28\r\n~SD14\r\n^PR10\r\n'
    '^FO30,30 ^BXN,6,200,,,,\\,1 ^FD{datamatrix}^FS\r\n\r\n^XZ'
)

# Код с «проблемными» для ^BX quality 200 символами: подчёркивание (escape)
# и GS-разделитель \x1d.
CODE = '0104601751028662215a_b1!\x1d93wr1V'


def _render_template(code: str) -> str:
    zpl = substitute_placeholders(
        TEMPLATE,
        batch_number='1564',
        marking_date=date(2026, 10, 7),
        expiration_date=date(2026, 10, 17),
        current_box=1,
        datamatrix=code,
    )
    return rasterize_datamatrix(zpl)


def _decode_gfa(zpl: str):
    """Восстановить изображение из ``^GFA`` и прочитать DataMatrix."""
    m = re.search(r'\^GFA,(\d+),(\d+),(\d+),([0-9A-Fa-f]+)\^FS', zpl)
    assert m, 'в ZPL нет ^GFA'
    total, _graphic, bytes_per_row = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hex_data = m.group(4)
    data = bytes.fromhex(hex_data)
    assert len(data) == total

    width = bytes_per_row * 8
    height = total // bytes_per_row
    # Тихая зона в растр не входит (в печати её роль играет белое поле
    # этикетки), для декодера добавляем рамку.
    margin = 20
    img = Image.new('L', (width + 2 * margin, height + 2 * margin), 255)
    px = img.load()
    for row in range(height):
        row_bytes = data[row * bytes_per_row:(row + 1) * bytes_per_row]
        for col, byte in enumerate(row_bytes):
            for bit in range(8):
                if byte & (0x80 >> bit):
                    px[col * 8 + bit + margin, row + margin] = 0
    return dmtx_decode(img)


def test_bx_replaced_with_raster():
    out = _render_template(CODE)
    assert '^BX' not in out
    assert '^GFA,' in out
    assert CODE not in out  # сам код не отправляется принтеру на кодирование


def test_raster_decodes_back_to_code_with_underscore_and_gs():
    out = _render_template(CODE)
    decoded = _decode_gfa(out)
    assert decoded, 'растр должен читаться как DataMatrix'
    # CODE — GS1-строка: разделитель GS (\x1d) кодируется как FNC1 и при
    # чтении не выводится отдельным символом.
    assert decoded[0].data.decode('latin-1') == CODE.replace('\x1d', '')


def test_raster_matches_dot_size_of_bx():
    """Размер растра = число модулей × размер модуля (h=6 из ^BX)."""
    out = _render_template(CODE)
    m = re.search(r'\^GFA,(\d+),(\d+),(\d+),', out)
    total, _graphic, bytes_per_row = int(m.group(1)), int(m.group(2)), int(m.group(3))
    height = total // bytes_per_row
    width = bytes_per_row * 8
    assert width % 6 == 0 and height % 6 == 0


def test_uip_template_is_rasterized_too():
    """UIP-шаблоны (цифровой ^BX) также печатаются растром — без ^BX."""
    from types import SimpleNamespace
    from helpers.printers import build_product_zpl

    uip_zpl = (
        '^XA^FO20,340^BXN,2,200^FD'
        '{uip_gtin}{uip_marking_date}{uip_article}{uip_batch}^FS^XZ'
    )
    product = SimpleNamespace(
        gtin='04600000000017', gtin_unit='04600000000024',
        article='AB12', date_expiration=10,
    )
    zpl = build_product_zpl(
        uip_zpl, product=product, batch_number='1564',
        marking_date=date(2026, 3, 5), current_box=1, uip_include_batch=True,
    )
    out = rasterize_datamatrix(zpl)
    assert '^BX' not in out
    assert '^GFA,' in out


def test_zpl_without_datamatrix_unchanged():
    zpl = '^XA^FO10,10^FDTEXT^FS^XZ'
    assert rasterize_datamatrix(zpl) == zpl


def test_empty_datamatrix_field_left_unchanged():
    zpl = '^XA^FO10,10^BXN,4,200^FD^FS^XZ'
    out = rasterize_datamatrix(zpl)
    assert out == zpl  # пустое поле не трогаем (как и replace_*)


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
