# test_datamatrix_layout.py
"""Тесты раскладки DataMatrix для интерактивного редактора шаблонов.

Проверяем разбор размера этикетки, ^LH, координат/размера полей ^BX и
подстановку образца данных вместо плейсхолдера {datamatrix}. Всё локально,
без сети и БД.
"""

import pytest

from services.datamatrix_renderer import (
    datamatrix_fields_layout,
    datamatrix_size_dots,
    label_home_dots,
    label_size_dots,
)

SAMPLE = '010460999000001121000001\x1d930001'

# Пробел после ^FO и «странный» escape-параметр \, — как в реальных шаблонах.
ZPL_ONE = r'^XA^PW160^LL160^FO30,30 ^BXN,5,200,,,\,1 ^FD{datamatrix}^FS^XZ'


def test_label_size_from_pw_ll():
    assert label_size_dots(ZPL_ONE) == (160, 160)


def test_label_size_default_when_absent():
    w, h = label_size_dots('^XA^FO0,0^FDx^FS^XZ')
    assert (w, h) == (813, 1219)


def test_label_home_default():
    assert label_home_dots('^XA^FO0,0^FDx^FS^XZ') == (0, 0)


def test_label_home_parsed():
    assert label_home_dots('^XA^LH10,20^FO0,0^FDx^FS^XZ') == (10, 20)


def test_single_field_position_and_module():
    layout = datamatrix_fields_layout(ZPL_ONE, sample_data=SAMPLE)
    assert layout['label_w'] == 160
    assert layout['label_h'] == 160
    assert len(layout['fields']) == 1
    field = layout['fields'][0]
    assert field['index'] == 0
    assert field['x'] == 30 and field['y'] == 30
    assert field['module'] == 5
    assert field['orient'] == 'N'
    assert (field['w'], field['h']) == datamatrix_size_dots(SAMPLE, 5, 'N')


def test_sample_data_used_for_placeholder():
    """Размер рамки берётся от образца, а не от литерала {datamatrix}."""
    with_sample = datamatrix_fields_layout(ZPL_ONE, sample_data=SAMPLE)
    without_sample = datamatrix_fields_layout(ZPL_ONE)
    # Размеры для разных данных, как правило, различаются — проверяем, что
    # образец реально подставился (ширина равна размеру образца).
    assert with_sample['fields'][0]['w'] == datamatrix_size_dots(SAMPLE, 5, 'N')[0]
    assert without_sample['fields'][0]['w'] > 0


def test_multiple_fields_have_indices():
    zpl = (
        r'^XA^PW400^LL400'
        r'^FO10,10^BXN,4,200,,,\,1^FD{datamatrix}^FS'
        r'^FO200,200^BXN,6,200,,,\,1^FD{datamatrix}^FS'
        r'^XZ'
    )
    layout = datamatrix_fields_layout(zpl, sample_data=SAMPLE)
    assert [f['index'] for f in layout['fields']] == [0, 1]
    assert layout['fields'][0]['x'] == 10 and layout['fields'][0]['module'] == 4
    assert layout['fields'][1]['x'] == 200 and layout['fields'][1]['module'] == 6


def test_no_datamatrix_returns_empty_fields():
    layout = datamatrix_fields_layout('^XA^FO0,0^FDtext^FS^XZ')
    assert layout['fields'] == []


def test_label_home_included_in_layout():
    zpl = r'^XA^LH5,7^FO10,20^BXN,4,200,,,\,1^FD{datamatrix}^FS^XZ'
    layout = datamatrix_fields_layout(zpl, sample_data=SAMPLE)
    assert (layout['lh_x'], layout['lh_y']) == (5, 7)
    assert layout['fields'][0]['x'] == 10 and layout['fields'][0]['y'] == 20


def test_size_dots_orientation_swaps_square_is_stable():
    w_n, h_n = datamatrix_size_dots(SAMPLE, 5, 'N')
    w_r, h_r = datamatrix_size_dots(SAMPLE, 5, 'R')
    # Символ квадратный, поэтому поворот не меняет размеры.
    assert (w_n, h_n) == (w_r, h_r)


def test_size_dots_scales_with_module():
    w4, _ = datamatrix_size_dots(SAMPLE, 4, 'N')
    w8, _ = datamatrix_size_dots(SAMPLE, 8, 'N')
    assert w8 == w4 * 2


def test_layout_with_real_preview_sample():
    """Раскладка совместима с образцом кода, который рисует превью."""
    from routers.template import _sample_datamatrix_code

    sample = _sample_datamatrix_code('04609990000011')
    layout = datamatrix_fields_layout(ZPL_ONE, sample_data=sample)
    assert len(layout['fields']) == 1
    assert layout['fields'][0]['w'] == datamatrix_size_dots(sample, 5, 'N')[0]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
