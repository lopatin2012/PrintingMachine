"""Назначение шаблона (label_type): unit — потребительская упаковка, group — групповая/набор.

От назначения зависит, какой шаблон отдаёт публичный API:
`/api/printing/zpl-unit` берёт `unit`, `/api/printing/zpl` — `group`
(`routers/print_job.py:_build_zpl_response`).
"""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from schemas import (
    LABEL_TYPES,
    CodeTemplateCreate,
    CodeTemplateUpdate,
    normalize_label_type,
)


def _template_kwargs(**extra):
    return dict(
        product_id=uuid4(),
        printer_id=uuid4(),
        name='Шаблон',
        print_code='^XA^XZ',
        **extra,
    )


def test_label_types_are_unit_and_group():
    assert set(LABEL_TYPES) == {'unit', 'group'}


def test_empty_defaults_to_group():
    assert normalize_label_type(None) == 'group'
    assert normalize_label_type('') == 'group'
    assert normalize_label_type('   ') == 'group'


def test_accepts_unit_and_group_in_any_case():
    assert normalize_label_type('unit') == 'unit'
    assert normalize_label_type('GROUP') == 'group'
    assert normalize_label_type(' Unit ') == 'unit'


def test_unknown_value_rejected():
    with pytest.raises(ValueError):
        normalize_label_type('pallet')


def test_create_defaults_to_group():
    assert CodeTemplateCreate(**_template_kwargs()).label_type == 'group'


def test_create_with_unit():
    assert CodeTemplateCreate(**_template_kwargs(label_type='unit')).label_type == 'unit'


def test_create_rejects_unknown():
    with pytest.raises(ValidationError):
        CodeTemplateCreate(**_template_kwargs(label_type='pallet'))


def test_update_is_optional():
    assert CodeTemplateUpdate().label_type is None
    assert CodeTemplateUpdate(label_type='unit').label_type == 'unit'


def test_update_rejects_unknown():
    with pytest.raises(ValidationError):
        CodeTemplateUpdate(label_type='pallet')
