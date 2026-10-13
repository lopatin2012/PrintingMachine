# test_datamatrix_renderer.py
"""Тесты собственного отрисовщика DataMatrix (services/datamatrix_renderer.py).

Проверяем, что символ кодируется локально (без Labelary), корректно
считывается обратно, масштабируется/поворачивается и упаковывается в
ZPL-графику ``^GF`` для подмены ``^BX`` в превью.
"""

import io

import pytest
from PIL import Image
from pylibdmtx.pylibdmtx import decode as dmtx_decode

from services.datamatrix_renderer import (
    DataMatrixEncodeError,
    DEFAULT_QUIET_ZONE,
    datamatrix_to_zpl_gfa,
    encode_datamatrix,
    is_gs1_data,
    module_dots_from_zpl,
    render_datamatrix_image,
    replace_datamatrix_with_graphics,
)

CODE = '0104601751020529215TsqZb\x1d93wdcS'


def test_encode_returns_square_binary_matrix():
    matrix = encode_datamatrix(CODE)
    assert len(matrix) == len(matrix[0])
    assert len(matrix) >= 10
    for row in matrix:
        assert set(row) <= {0, 1}


def test_empty_data_raises():
    with pytest.raises(DataMatrixEncodeError):
        encode_datamatrix('')


def test_rendered_symbol_decodes_back():
    img = render_datamatrix_image(CODE, module_px=6)
    decoded = dmtx_decode(img)
    assert decoded, 'символ DataMatrix должен читаться'
    # CODE — GS1-строка: разделитель GS (\x1d) кодируется как FNC1 и при
    # чтении не выводится отдельным символом.
    assert decoded[0].data.decode('latin-1') == CODE.replace('\x1d', '')


def test_gs1_string_is_detected():
    """Внешние коды (AI 01 + GTIN14) распознаются как GS1."""
    assert is_gs1_data(CODE)
    assert is_gs1_data('0104601751027529215TsqZb')  # без разделителя — тоже GS1


def test_gs1_fnc1_is_applied():
    """GS1-символ: разделитель закодирован как FNC1 (при чтении не виден)."""
    img = render_datamatrix_image(CODE, module_px=6, quiet_zone=4)
    decoded = dmtx_decode(img)
    assert decoded
    data = decoded[0].data.decode('latin-1')
    assert '\x1d' not in data
    assert data == CODE.replace('\x1d', '')


def test_non_gs1_is_not_detected():
    """УИП (начинается с GTIN, без AI 01) под GS1 не попадает."""
    assert not is_gs1_data('0460175102866226100101AB120000000000000')
    assert not is_gs1_data('04609990000011')


def test_image_size_matches_modules_and_quiet_zone():
    matrix = encode_datamatrix(CODE)
    cols, rows = len(matrix[0]), len(matrix)
    img = render_datamatrix_image(CODE, module_px=4, quiet_zone=2)
    assert img.size == ((cols + 2 * 2) * 4, (rows + 2 * 2) * 4)


def test_orientation_does_not_break_symbol():
    for orient in ('N', 'R', 'I', 'B'):
        img = render_datamatrix_image(CODE, module_px=5, orient=orient)
        decoded = dmtx_decode(img)
        assert decoded, f'ориентация {orient} не должна ломать символ'


def test_gfa_format():
    gfa, w, h = datamatrix_to_zpl_gfa(
        CODE, origin_x=10, origin_y=20, module_dots=4,
    )
    assert gfa.startswith('^FO10,20^GFA,')
    assert gfa.endswith('^FS')
    # b (бинарные байты) == c (графических байт) == total
    head = gfa.split('^GFA,', 1)[1].split(',', 3)
    total, graphic, bpr = int(head[0]), int(head[1]), int(head[2])
    assert total == graphic
    assert bpr == (w + 7) // 8
    # Высота (в точках) = число строк данных × модуль; total = байт/строку × точек.
    data_bytes = total
    assert data_bytes == bpr * h
    assert h > 0


def test_replace_bx_with_gf():
    zpl = (
        '^XA^PW812^LL406^FO50,50^BXR,4,200,,,^FD' + CODE + '^FS^XZ'
    )
    out, count = replace_datamatrix_with_graphics(zpl)
    assert count == 1
    assert '^BX' not in out
    assert '^GFA,' in out
    assert out.startswith('^XA')


def test_replace_leaves_non_datamatrix_untouched():
    zpl = '^XA^FO10,10^BCN,100,Y^FD123456^FS^XZ'
    out, count = replace_datamatrix_with_graphics(zpl)
    assert count == 0
    assert out == zpl


def test_replace_decodes_fh_hex_data():
    # GS (0x1D) закодирован как _1D при ^FH.
    zpl = (
        '^XA^FO10,10^BXN,4,200^FH^FD'
        '0104601751020529215TsqZb_1D93wdcS^FS^XZ'
    )
    out, count = replace_datamatrix_with_graphics(zpl)
    assert count == 1
    assert '^GFA,' in out


def test_replace_empty_field_is_kept():
    zpl = '^XA^FO10,10^BXN,4,200^FD^FS^XZ'
    out, count = replace_datamatrix_with_graphics(zpl)
    assert count == 0
    assert '^BX' in out


def test_module_dots_from_zpl():
    assert module_dots_from_zpl('^XA^FO50,50^BXR,4,200,,,^FDx^FS^XZ') == 4
    assert module_dots_from_zpl('^XA^FO50,50^BXR,8,200,,,^FDx^FS^XZ') == 8
    assert module_dots_from_zpl('^XA^FO1,1^BCN,100^FDx^FS^XZ', default=5) == 5
    assert module_dots_from_zpl('', default=7) == 7


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
