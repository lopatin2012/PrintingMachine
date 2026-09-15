# test_build_product_zpl.py
"""Тесты сборки ZPL по продукту (helpers/printers.py:build_product_zpl).

Публичный API отдачи ZPL по GTIN групповой упаковки подставляет данные из
продукта (GTIN, GTIN единицы, артикул, срок годности), а недостающие (партия,
дата маркировки, номер коробки) берёт из query-параметров. Тесты проверяют
подстановку и вычисление срока годности без БД.
"""

from datetime import date
from types import SimpleNamespace

from helpers.printers import build_product_zpl


ZPL = (
    '^XA\n'
    '^FO20,90^BCN,150,Y,N,N,N^FD'
    '{gs1_128_marking_date}{gs1_128_expiry_date}{gs1_gs}'
    '{gs1_128_batch}{gs1_gs}{gs1_128_current_box}{gs1_gs}{gs1_gtin}^FS\n'
    '^FO20,340^BXN,2,200^FD{uip_gtin}{uip_marking_date}{uip_article}{uip_batch}^FS\n'
    '^XZ'
)


def _product(**overrides):
    data = {
        'gtin': '04600000000017',
        'gtin_unit': '04600000000024',
        'article': 'AB12',
        'date_expiration': 10,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_product_data_substituted():
    zpl = build_product_zpl(
        ZPL,
        product=_product(),
        batch_number='1564',
        marking_date=date(2026, 3, 5),
        current_box=1,
        uip_include_batch=True,
    )
    assert '{gs1_gtin}' not in zpl
    assert '{uip_gtin}' not in zpl
    assert '{uip_article}' not in zpl
    assert '04600000000017' in zpl
    assert '04600000000024' in zpl
    assert 'AB12' in zpl


def test_query_data_used_for_missing_fields():
    zpl = build_product_zpl(
        ZPL,
        product=_product(),
        batch_number='1564',
        marking_date=date(2026, 3, 5),
        current_box=7,
        uip_include_batch=True,
    )
    assert '260305' in zpl          # marking_date YYMMDD
    assert '050326' in zpl          # batch = marking_date DDMMYY
    assert '00007' in zpl           # current_box 5 знаков


def test_expiration_computed_from_product():
    zpl = build_product_zpl(
        ZPL,
        product=_product(date_expiration=10),
        batch_number='1564',
        marking_date=date(2026, 3, 5),
        current_box=1,
    )
    assert '260315' in zpl          # 05.03.2026 + 10 дней = 15.03.2026


def test_xz_appended_when_missing():
    zpl = build_product_zpl(
        '^XA^FO10,10^FDX^FS',
        product=_product(),
        batch_number='1',
        marking_date=date(2026, 3, 5),
    )
    assert zpl.strip().endswith('^XZ')


def test_uip_without_batch_is_zeros():
    zpl = build_product_zpl(
        '^XA^FD{uip_batch}^FS',
        product=_product(),
        batch_number='1564',
        marking_date=date(2026, 3, 5),
        uip_include_batch=False,
    )
    assert '1564' not in zpl
    assert '0' * 12 in zpl


def test_empty_gtin_unit_removes_placeholder():
    zpl = build_product_zpl(
        '^XA^FD{uip_gtin}^FS',
        product=_product(gtin_unit=None),
        batch_number='1',
        marking_date=date(2026, 3, 5),
    )
    assert '{uip_gtin}' not in zpl
