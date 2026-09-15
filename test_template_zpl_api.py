# test_template_zpl_api.py
"""Тесты REST-метода выдачи ZPL активного шаблона по GTIN групповой упаковки.

БД не требуется: CRUD-методы подменяются заглушками.
"""

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import routers.template as template_router


GTIN = '04680000000001'


def _product(**overrides):
    data = dict(
        id='pid',
        gtin=GTIN,
        gtin_unit='04680000000002',
        article='ART-1',
        name='Продукт',
        date_expiration=30,
        name_line1='Строка 1',
        name_line2='Строка 2',
        tu_number='ТУ 1',
        weight='40г',
        fat_content='16%',
        units_count='6шт',
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def _template(**overrides):
    data = dict(
        id='tid',
        name='Шаблон',
        print_code='^XA^FD{gs1_gtin}^FS^FD{product_name}^FS^FD{weight}^FS^XZ',
        uip_include_batch=False,
        is_print_gtin_unit=True,
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def _patch(monkeypatch, *, product, template):
    async def fake_get_by_gtin(db, gtin):
        return product

    async def fake_get_active(db, product_id):
        return template

    monkeypatch.setattr(
        template_router.product_crud, 'get_by_gtin', fake_get_by_gtin
    )
    monkeypatch.setattr(
        template_router.template_crud, 'get_active_by_product', fake_get_active
    )


def test_substitutes_product_placeholders(monkeypatch):
    _patch(monkeypatch, product=_product(), template=_template())

    result = asyncio.run(
        template_router.get_active_template_zpl(
            GTIN,
            batch_number='1564',
            marking_date=date(2026, 3, 5),
            current_box=1,
            datamatrix='',
            db=None,
            current_user=None,
        )
    )

    assert result['success'] is True
    assert result['gtin'] == GTIN
    assert result['template_id'] == 'tid'
    assert result['zpl'] == (
        f'^XA^FD{GTIN}^FS^FDПродукт^FS^FD40г^FS^XZ'
    )
    assert '{' not in result['zpl']
    assert result['expiration_date'] == '2026-04-04'


def test_product_not_found(monkeypatch):
    _patch(monkeypatch, product=None, template=None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            template_router.get_active_template_zpl(
                GTIN, db=None, current_user=None
            )
        )

    assert exc.value.status_code == 404


def test_no_active_template(monkeypatch):
    _patch(monkeypatch, product=_product(), template=None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            template_router.get_active_template_zpl(
                GTIN, db=None, current_user=None
            )
        )

    assert exc.value.status_code == 404
