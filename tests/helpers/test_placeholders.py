# test_placeholders.py
"""Тесты подсказки по плейсхолдерам (helpers/printers.py).

compute_placeholder_values() возвращает значения, которые редактор шаблонов
показывает при наведении на кнопку «Плейсхолдеры». Тесты проверяют, что
значения совпадают с реальной подстановкой substitute_placeholders() и что
описание PLACEHOLDER_INFO покрывает весь набор плейсхолдеров.
"""

from datetime import date

from helpers.printers import (
    PLACEHOLDER_INFO,
    compute_placeholder_values,
    substitute_placeholders,
)

BATCH = '1564'
MARK = date(2026, 3, 5)
EXP = date(2026, 3, 15)
DATAMATRIX = '010460000000002421PREVIEW00001\x1d93DEMO'

GTIN = '04600000000017'
GTIN_UNIT = '04600000000024'
ARTICLE = 'AB12'

# Шаблон со всеми известными плейсхолдерами, каждый обрамлён | для точной
# проверки подставленного значения.
ALL_TEMPLATE = '^XA' + ''.join(f'|{p}|' for p, _ in PLACEHOLDER_INFO) + '^XZ'


def _kwargs(**overrides):
    data = dict(
        batch_number=BATCH,
        marking_date=MARK,
        expiration_date=EXP,
        current_box=7,
        gtin=GTIN,
        gtin_unit=GTIN_UNIT,
        article=ARTICLE,
        uip_include_batch=True,
        datamatrix=DATAMATRIX,
    )
    data.update(overrides)
    return data


def test_all_known_placeholders_have_values():
    values = compute_placeholder_values(ALL_TEMPLATE, **_kwargs())
    for placeholder, _ in PLACEHOLDER_INFO:
        assert placeholder in values


def test_values_match_substitution():
    kwargs = _kwargs()
    values = compute_placeholder_values(ALL_TEMPLATE, **kwargs)
    result = substitute_placeholders(ALL_TEMPLATE, **kwargs)

    # Каждое вычисленное значение реально подставлено.
    for placeholder, value in values.items():
        assert f'|{value}|' in result, placeholder

    # Не осталось незаменённых плейсхолдеров.
    assert '{' not in result


def test_current_box_is_five_digits():
    values = compute_placeholder_values(ALL_TEMPLATE, **_kwargs(current_box=7))
    assert values['{current_box}'] == '00007'
    assert values['{gs1_128_current_box}'] == '00007'


def test_dates_formats():
    values = compute_placeholder_values(ALL_TEMPLATE, **_kwargs())
    assert values['{marking_date_str}'] == '05.03.26'
    assert values['{expiration_date_str}'] == '15.03.26'
    assert values['{gs1_128_marking_date}'] == '260305'
    assert values['{gs1_128_expiry_date}'] == '260315'
    assert values['{gs1_128_expiration_date}'] == '260315'
    assert values['{gs1_128_batch}'] == '050326'
    assert values['{gs1_128_batch_number}'] == '050326'
    assert values['{batch_number_str}'] == '1564(050326)'


def test_gs_separator_is_group_separator():
    values = compute_placeholder_values(ALL_TEMPLATE, **_kwargs())
    assert values['{gs1_gs}'] == '\x1d'


def test_gtin_short_drops_leading_zero():
    values = compute_placeholder_values(ALL_TEMPLATE, **_kwargs())
    assert values['{gs1_gtin}'] == GTIN
    assert values['{gs1_gtin_short}'] == GTIN[1:]


def test_empty_gtin_values_are_blank():
    values = compute_placeholder_values(ALL_TEMPLATE, **_kwargs(gtin='', gtin_unit=''))
    assert values['{gs1_gtin}'] == ''
    assert values['{gs1_gtin_short}'] == ''
    assert values['{uip_gtin}'] == ''


def test_uip_batch_length_depends_on_article_placeholder():
    # Артикул есть в шаблоне: серийная часть = 32 - 14 - 6 - 4 = 8 знаков.
    with_article = compute_placeholder_values(ALL_TEMPLATE, **_kwargs())
    assert with_article['{uip_batch}'] == '15640000'

    # Артикул не в шаблоне: свободны 12 знаков.
    no_article_template = '^XA^FD{uip_batch}^FS^XZ'
    without_article = compute_placeholder_values(no_article_template, **_kwargs())
    assert without_article['{uip_batch}'] == '156400000000'


def test_uip_batch_zeros_when_batch_excluded():
    values = compute_placeholder_values(
        ALL_TEMPLATE, **_kwargs(uip_include_batch=False),
    )
    assert set(values['{uip_batch}']) == {'0'}
    assert len(values['{uip_batch}']) == 8


def test_datamatrix_value_passed_through():
    values = compute_placeholder_values(ALL_TEMPLATE, **_kwargs())
    assert values['{datamatrix}'] == DATAMATRIX
