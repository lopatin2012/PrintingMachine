# test_datamatrix_renderer.py
"""Тесты собственного движка DataMatrix ECC200 (services/datamatrix_renderer.py).

Проверяем кодирование (ASCII, цифровые пары, extended ASCII), Reed-Solomon,
размещение, размеры символов и то, что отрисованный код декодируется обратно
(pylibdmtx используется только как независимый декодер-эталон в тестах).
"""

import pytest

from services.datamatrix_renderer import (
    DataMatrixError,
    build_matrix,
    data_to_image,
    encode_ascii,
)

# pylibdmtx нужен только для проверки декодирования.
try:
    from pylibdmtx.pylibdmtx import decode as _dmtx_decode
    HAS_DECODER = True
except Exception:  # pragma: no cover
    _dmtx_decode = None
    HAS_DECODER = False


def _decode(image):
    if not HAS_DECODER:
        pytest.skip('pylibdmtx недоступен для проверки декодирования')
    result = _dmtx_decode(image, timeout=8000)
    return result[0].data if result else None


# ---------------------------------------------------------------------------
# Кодирование
# ---------------------------------------------------------------------------

def test_encode_ascii_digit_pairs():
    # '12' -> одна цифровая пара 130 + 12 = 142
    assert encode_ascii(b'12') == [142]
    # '123' -> пара '12' (142) + '3' (51+1)
    assert encode_ascii(b'123') == [142, 52]


def test_encode_ascii_control_and_extended():
    # GS (0x1D) как FNC1 (232)
    assert 232 in encode_ascii(b'\x1d', gs_as_fnc1=True)
    # literal-GS -> обычный контрольный символ 0x1D + 1 = 30
    assert encode_ascii(b'\x1d', gs_as_fnc1=False) == [30]
    # extended ASCII: 0xFF -> Upper Shift (235), 0xFF-128+1 = 128
    assert encode_ascii(b'\xff') == [235, 128]


# ---------------------------------------------------------------------------
# Размеры символов ECC200
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('length,expected', [
    (1, 10),
    (5, 12),
    (12, 16),
    (40, 26),
    (80, 36),
    (150, 48),
])
def test_symbol_sizes(length, expected):
    data = (b'AB' * length)[:length]
    matrix = build_matrix(data)
    assert len(matrix) == expected
    assert all(len(row) == expected for row in matrix)


def test_empty_data_raises():
    with pytest.raises(DataMatrixError):
        build_matrix(b'')


def test_oversized_data_raises():
    with pytest.raises(DataMatrixError):
        build_matrix(b'A' * 5000)


# ---------------------------------------------------------------------------
# Структура: finder/clock-паттерны
# ---------------------------------------------------------------------------

def test_finder_patterns():
    matrix = build_matrix(b'TEST-12345')
    n = len(matrix)
    # Верхняя строка — чередующаяся (finder), начинается с чёрного модуля.
    assert matrix[0] == [i % 2 == 0 for i in range(n)]
    # Правый столбец — чередующаяся (начинается с белого на первой строке).
    assert [matrix[r][n - 1] for r in range(n)] == [r % 2 != 0 for r in range(n)]
    # Левый столбец и нижняя строка — сплошные (clock).
    assert all(matrix[r][0] for r in range(n))
    assert all(matrix[n - 1][c] for c in range(n))


# ---------------------------------------------------------------------------
# Round-trip: отрисованный код должен декодироваться в исходные данные
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('payload', [
    b'HELLO',
    b'hello world',
    b'1234567890',
    b'010460175101874821T142TS0000002\x1d93xopKozxWTg9uDNHr8gtyOBUZwtoD2PMhiXd++MMVf3o=',
    bytes(range(1, 120)),
])
def test_roundtrip_decodes(payload):
    image = data_to_image(payload, module_px=5)
    assert _decode(image) == payload


def test_roundtrip_various_sizes():
    for n in (1, 5, 20, 80, 300, 1000, 1555):
        data = (b'XY' * n)[:n]
        image = data_to_image(data, module_px=3)
        assert _decode(image) == data, f'failed at length {n}'


def test_rendered_module_is_square():
    image = data_to_image(b'TEST', module_px=4)
    assert image.width == image.height
    # 12 модулей символа + 2 модуля поля покоя = 14 * 4
    assert image.width == 14 * 4
