"""Проверка флага «выключить позиционирование DataMatrix».

При включённом флаге предпросмотр не отдаёт заголовок X-DM-Layout,
поэтому в редакторе не рисуются рамки и координаты DataMatrix.
"""
import json
from uuid import uuid4

from schemas import CodeTemplateCreate, CodeTemplateUpdate
from routers.template import build_dm_layout_header


DM_ZPL = (
    '^XA\n'
    '^PW600\n'
    '^LL400\n'
    '^FO50,60^BXN,10,200^FD010460000000001721ABC^FS\n'
    '^XZ'
)


def test_layout_header_contains_datamatrix_field():
    header = build_dm_layout_header(DM_ZPL, '0104600000000017')
    assert header
    layout = json.loads(header)
    assert layout['fields']
    assert layout['fields'][0]['x'] == 50
    assert layout['fields'][0]['y'] == 60


def test_layout_header_is_empty_when_positioning_disabled():
    assert build_dm_layout_header(
        DM_ZPL, '0104600000000017', disable_positioning=True
    ) is None


def test_create_schema_defaults_positioning_enabled():
    template = CodeTemplateCreate(
        product_id=uuid4(),
        printer_id=uuid4(),
        name='Шаблон',
        print_code='^XA^XZ',
    )
    assert template.disable_dm_positioning is False


def test_update_schema_flag_is_optional():
    assert CodeTemplateUpdate().disable_dm_positioning is None
