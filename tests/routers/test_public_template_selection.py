"""Выбор шаблона печати: публичный список и template_id в выдаче ZPL."""
import asyncio
from datetime import date
from uuid import uuid4

import pytest
from fastapi import HTTPException

from models import CodeTemplate, Product
from routers.print_job import _build_zpl_response, _template_list_item


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeDB:
    """Минимальная заглушка AsyncSession: возвращает заранее заданные значения."""

    def __init__(self, *values):
        self._values = iter(values)

    async def execute(self, query):
        return _Result(next(self._values))


def _product() -> Product:
    return Product(
        id=uuid4(),
        article='A1',
        name='Набор',
        gtin='04601751030566',
        gtin_unit=None,
        date_expiration=30,
    )


def _template(product: Product, *, name: str = 'Шаблон', code: str = '^XA^XZ') -> CodeTemplate:
    return CodeTemplate(
        id=uuid4(),
        product_id=product.id,
        printer_id=uuid4(),
        name=name,
        print_code=code,
        is_active=True,
        label_type='group',
        uip_include_batch=False,
        is_print_gtin_unit=False,
    )


def _response(db: _FakeDB, product: Product, template_id=None):
    return asyncio.run(_build_zpl_response(
        db,
        product,
        label_type='group',
        batch_number='01',
        marking_date=date(2026, 11, 16),
        first_box=1,
        printer_id=None,
        template_id=template_id,
    ))


def test_template_id_selects_exact_template():
    product = _product()
    template = _template(product, name='Второй шаблон')
    response = _response(_FakeDB(template), product, template_id=template.id)

    assert response['template_id'] == str(template.id)
    assert response['template_name'] == 'Второй шаблон'


def test_unknown_template_id_returns_404():
    product = _product()
    with pytest.raises(HTTPException) as exc:
        _response(_FakeDB(None), product, template_id=uuid4())

    assert exc.value.status_code == 404
    assert 'template_id' in exc.value.detail


def test_expiration_date_from_task_overrides_calculation():
    product = _product()
    template = _template(product)
    response = asyncio.run(_build_zpl_response(
        _FakeDB(template),
        product,
        label_type='group',
        batch_number='01',
        marking_date=date(2026, 11, 16),
        first_box=1,
        printer_id=None,
        template_id=None,
        expiration_date=date(2026, 12, 11),
    ))

    assert response['expiration_date'] == '2026-12-11'


def test_template_list_item_marks_set_datamatrix():
    product = _product()
    set_template = _template(product, code='^XA^FD{datamatrix_s}^FS^XZ')
    ready_template = _template(
        product,
        code='^XA^FO19,162^BXN,3,200,,,,\\,1^FD0104601751016584215SAMPLE^FS^XZ',
    )
    box_template = _template(product, code='^XA^FD{datamatrix_g}^FS^XZ')
    ean_template = _template(
        product,
        code='^XA^FO554,12^BY2^BEN,30,Y,N^FD4601751030566^FS^XZ',
    )

    item = _template_list_item(set_template)
    assert item['id'] == str(set_template.id)
    assert item['name'] == 'Шаблон'
    assert item['has_datamatrix_s'] is True
    # Готовое поле DataMatrix без {datamatrix_s} тоже пригодно для набора:
    # терминал заменит образец кода на реальный КИН.
    assert _template_list_item(ready_template)['has_datamatrix_s'] is True
    assert _template_list_item(box_template)['has_datamatrix_s'] is False
    assert _template_list_item(ean_template)['has_datamatrix_s'] is False
