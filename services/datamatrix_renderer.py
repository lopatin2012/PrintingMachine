# services/datamatrix_renderer.py
"""Собственный движок DataMatrix (ECC200): кодирование + отрисовка.

Без внешних зависимостей (Labelary, zplr, libdmtx/pylibdmtx): кодировщик
DataMatrix ECC200 и отрисовка модулей реализованы здесь на чистом Python.

Алгоритм соответствует ISO/IEC 16022 (ECC200) и портирован с эталонной
реализации ZXing (Apache-2.0):
  * ASCII-кодирование (цифровые пары, управляющие символы, extended ASCII);
  * Reed-Solomon ECC200 (GF(256), полином 0x12D, база 1);
  * размещение кодовых слов (DefaultPlacement, annex M.1);
  * сборка символа с finder/clock-паттернами (encodeLowLevel).

Поддерживаются все квадратные размеры ECC200 (10×10 … 144×144).

Пример:
    from services.datamatrix_renderer import render_datamatrix
    img = render_datamatrix(b'0104601751018748...', module_px=5)
"""

from __future__ import annotations

from PIL import Image, ImageDraw

# ---------------------------------------------------------------------------
# Таблица символов ECC200 (только квадратные).
# (data_capacity, error_codewords, matrix_w, matrix_h, data_regions, rs_data, rs_err)
# ---------------------------------------------------------------------------
_SQUARE_SYMBOLS: list[tuple[int, int, int, int, int, int, int]] = [
    (3, 5, 8, 8, 1, 3, 5),
    (5, 7, 10, 10, 1, 5, 7),
    (8, 10, 12, 12, 1, 8, 10),
    (12, 12, 14, 14, 1, 12, 12),
    (18, 14, 16, 16, 1, 18, 14),
    (22, 18, 18, 18, 1, 22, 18),
    (30, 20, 20, 20, 1, 30, 20),
    (36, 24, 22, 22, 1, 36, 24),
    (44, 28, 24, 24, 1, 44, 28),
    (62, 36, 14, 14, 4, 62, 36),
    (86, 42, 16, 16, 4, 86, 42),
    (114, 48, 18, 18, 4, 114, 48),
    (144, 56, 20, 20, 4, 144, 56),
    (174, 68, 22, 22, 4, 174, 68),
    (204, 84, 24, 24, 4, 102, 42),
    (280, 112, 14, 14, 16, 140, 56),
    (368, 144, 16, 16, 16, 92, 36),
    (456, 192, 18, 18, 16, 114, 48),
    (576, 224, 20, 20, 16, 144, 56),
    (696, 272, 22, 22, 16, 174, 68),
    (816, 336, 24, 24, 16, 136, 56),
    (1050, 408, 18, 18, 36, 175, 68),
    (1304, 496, 20, 20, 36, 163, 62),
    (1558, 620, 22, 22, 36, 156, 62),
]

# Reed-Solomon: фиксированные генераторные полиномы ECC200 (по числу EC-слов).
_FACTOR_SETS = [5, 7, 10, 11, 12, 14, 18, 20, 24, 28, 36, 42, 48, 56, 62, 68]
_FACTORS = [
    [228, 48, 15, 111, 62],
    [23, 68, 144, 134, 240, 92, 254],
    [28, 24, 185, 166, 223, 248, 116, 255, 110, 61],
    [175, 138, 205, 12, 194, 168, 39, 245, 60, 97, 120],
    [41, 153, 158, 91, 61, 42, 142, 213, 97, 178, 100, 242],
    [156, 97, 192, 252, 95, 9, 157, 119, 138, 45, 18, 186, 83, 185],
    [83, 195, 100, 39, 188, 75, 66, 61, 241, 213, 109, 129, 94, 254, 225, 48, 90, 188],
    [15, 195, 244, 9, 233, 71, 168, 2, 188, 160, 153, 145, 253, 79, 108, 82, 27, 174, 186, 172],
    [52, 190, 88, 205, 109, 39, 176, 21, 155, 197, 251, 223, 155, 21, 5, 172,
     254, 124, 12, 181, 184, 96, 50, 193],
    [211, 231, 43, 97, 71, 96, 103, 174, 37, 151, 170, 53, 75, 34, 249, 121,
     17, 138, 110, 213, 141, 136, 120, 151, 233, 168, 93, 255],
    [245, 127, 242, 218, 130, 250, 162, 181, 102, 120, 84, 179, 220, 251, 80, 182,
     229, 18, 2, 4, 68, 33, 101, 137, 95, 119, 115, 44, 175, 184, 59, 25,
     225, 98, 81, 112],
    [77, 193, 137, 31, 19, 38, 22, 153, 247, 105, 122, 2, 245, 133, 242, 8,
     175, 95, 100, 9, 167, 105, 214, 111, 57, 121, 21, 1, 253, 57, 54, 101,
     248, 202, 69, 50, 150, 177, 226, 5, 9, 5],
    [245, 132, 172, 223, 96, 32, 117, 22, 238, 133, 238, 231, 205, 188, 237, 87,
     191, 106, 16, 147, 118, 23, 37, 90, 170, 205, 131, 88, 120, 100, 66, 138,
     186, 240, 82, 44, 176, 87, 187, 147, 160, 175, 69, 213, 92, 253, 225, 19],
    [175, 9, 223, 238, 12, 17, 220, 208, 100, 29, 175, 170, 230, 192, 215, 235,
     150, 159, 36, 223, 38, 200, 132, 54, 228, 146, 218, 234, 117, 203, 29, 232,
     144, 238, 22, 150, 201, 117, 62, 207, 164, 13, 137, 245, 127, 67, 247, 28,
     155, 43, 203, 107, 233, 53, 143, 46],
    [242, 93, 169, 50, 144, 210, 39, 118, 202, 188, 201, 189, 143, 108, 196, 37,
     185, 112, 134, 230, 245, 63, 197, 190, 250, 106, 185, 221, 175, 64, 114, 71,
     161, 44, 147, 6, 27, 218, 51, 63, 87, 10, 40, 130, 188, 17, 163, 31,
     176, 170, 4, 107, 232, 7, 94, 166, 224, 124, 86, 47, 11, 204],
    [220, 228, 173, 89, 251, 149, 159, 56, 89, 33, 147, 244, 154, 36, 73, 127,
     213, 136, 248, 180, 234, 197, 158, 177, 68, 122, 93, 213, 15, 160, 227, 236,
     66, 139, 153, 185, 202, 167, 179, 25, 220, 232, 96, 210, 231, 136, 223, 239,
     181, 241, 59, 52, 172, 25, 49, 232, 211, 189, 64, 54, 108, 153, 132, 63,
     96, 103, 82, 186],
]

_MODULO_VALUE = 0x12D

# Таблицы логарифмов/антилогарифмов поля GF(256).
_LOG = [0] * 256
_ALOG = [0] * 255
_p = 1
for _i in range(255):
    _ALOG[_i] = _p
    _LOG[_p] = _i
    _p *= 2
    if _p >= 256:
        _p ^= _MODULO_VALUE
del _p, _i


class DataMatrixError(Exception):
    """Ошибка кодирования DataMatrix (данные не помещаются и т.п.)."""


# ---------------------------------------------------------------------------
# Кодирование сообщения (ASCII)
# ---------------------------------------------------------------------------

def encode_ascii(data: bytes, gs_as_fnc1: bool = True) -> list[int]:
    """ASCII-кодирование (annex P): цифровые пары, extended ASCII, FNC1 (232).

    gs_as_fnc1: трактовать байт GS (0x1D) как FNC1 (232). Если False — как
    обычный управляющий символ ASCII (значение 30). Нужно для совпадения с
    конкретным движком (Labelary/Zebra).
    """
    codewords: list[int] = []
    i = 0
    n = len(data)
    while i < n:
        # Число подряд идущих цифр.
        j = i
        while j < n and 48 <= data[j] <= 57:  # '0'..'9'
            j += 1
        if j - i >= 2:
            value = (data[i] - 48) * 10 + (data[i + 1] - 48)
            codewords.append(130 + value)
            i += 2
        else:
            c = data[i]
            if c == 0x1D and gs_as_fnc1:  # GS1-разделитель -> FNC1
                codewords.append(232)
            elif c >= 128:                # extended ASCII
                codewords.append(235)
                codewords.append(c - 128 + 1)
            else:
                codewords.append(c + 1)
            i += 1
    return codewords


def _randomize253_state(codeword_position: int) -> int:
    """Псевдослучайное дополнение ECC200 (позиция 1-based)."""
    pseudo_random = ((149 * codeword_position) % 253) + 1
    temp = 129 + pseudo_random
    return temp if temp <= 254 else temp - 254


def _pad(codewords: list[int], capacity: int) -> list[int]:
    codewords = list(codewords)
    if len(codewords) < capacity:
        codewords.append(129)  # PAD
    while len(codewords) < capacity:
        codewords.append(_randomize253_state(len(codewords) + 1))
    return codewords


# ---------------------------------------------------------------------------
# Размер символа
# ---------------------------------------------------------------------------

def _lookup_symbol(data_codewords: int) -> tuple[int, int, int, int, int, int, int]:
    for symbol in _SQUARE_SYMBOLS:
        if data_codewords <= symbol[0]:
            return symbol
    raise DataMatrixError(
        f'Данные не помещаются ни в один символ DataMatrix ({data_codewords} кодовых слов)'
    )


def _horizontal_regions(data_regions: int) -> int:
    return {1: 1, 4: 2, 16: 4, 36: 6}[data_regions]


def _vertical_regions(data_regions: int) -> int:
    return {1: 1, 4: 2, 16: 4, 36: 6}[data_regions]


def _interleaved_block_count(symbol) -> int:
    data_capacity, _ec, _mw, _mh, _regions, rs_data, _rs_err = symbol
    if data_capacity == 1558:
        return 10
    return data_capacity // rs_data


# ---------------------------------------------------------------------------
# Reed-Solomon ECC200
# ---------------------------------------------------------------------------

def _create_ecc_block(codewords, num_ec: int) -> list[int]:
    table = _FACTOR_SETS.index(num_ec)
    poly = _FACTORS[table]
    ecc = [0] * num_ec
    for cw in codewords:
        m = ecc[num_ec - 1] ^ cw
        for k in range(num_ec - 1, 0, -1):
            if m != 0 and poly[k] != 0:
                ecc[k] = ecc[k - 1] ^ _ALOG[(_LOG[m] + _LOG[poly[k]]) % 255]
            else:
                ecc[k] = ecc[k - 1]
        if m != 0 and poly[0] != 0:
            ecc[0] = _ALOG[(_LOG[m] + _LOG[poly[0]]) % 255]
        else:
            ecc[0] = 0
    return list(reversed(ecc))


def encode_ecc200(data_codewords: list[int], symbol) -> list[int]:
    """Добавить и перемежать ECC-слова ECC200."""
    data_capacity, error_codewords, _mw, _mh, _regions, rs_data, rs_err = symbol
    result = list(data_codewords) + [0] * error_codewords
    block_count = _interleaved_block_count(symbol)

    if block_count == 1:
        result[data_capacity:] = _create_ecc_block(data_codewords, error_codewords)
        return result

    for block in range(block_count):
        block_data = list(data_codewords[block::block_count])
        ecc = _create_ecc_block(block_data, rs_err)
        pos = 0
        for e in range(block, rs_err * block_count, block_count):
            result[data_capacity + e] = ecc[pos]
            pos += 1
    return result


# ---------------------------------------------------------------------------
# Размещение кодовых слов (ISO/IEC 16022, annex M.1 / ZXing DefaultPlacement)
# ---------------------------------------------------------------------------

def place_codewords(codewords: list[int], numcols: int, numrows: int) -> list[list[int]]:
    bits = [[-1] * numcols for _ in range(numrows)]

    def has_bit(col: int, row: int) -> bool:
        return bits[row][col] >= 0

    def set_bit(col: int, row: int, value: bool) -> None:
        bits[row][col] = 1 if value else 0

    def module(row: int, col: int, pos: int, bit: int) -> None:
        if row < 0:
            row += numrows
            col += 4 - ((numrows + 4) % 8)
        if col < 0:
            col += numcols
            row += 4 - ((numcols + 4) % 8)
        set_bit(col, row, bool(codewords[pos] & (1 << (8 - bit))))

    def utah(row: int, col: int, pos: int) -> None:
        module(row - 2, col - 2, pos, 1)
        module(row - 2, col - 1, pos, 2)
        module(row - 1, col - 2, pos, 3)
        module(row - 1, col - 1, pos, 4)
        module(row - 1, col, pos, 5)
        module(row, col - 2, pos, 6)
        module(row, col - 1, pos, 7)
        module(row, col, pos, 8)

    def corner1(pos: int) -> None:
        module(numrows - 1, 0, pos, 1)
        module(numrows - 1, 1, pos, 2)
        module(numrows - 1, 2, pos, 3)
        module(0, numcols - 2, pos, 4)
        module(0, numcols - 1, pos, 5)
        module(1, numcols - 1, pos, 6)
        module(2, numcols - 1, pos, 7)
        module(3, numcols - 1, pos, 8)

    def corner2(pos: int) -> None:
        module(numrows - 3, 0, pos, 1)
        module(numrows - 2, 0, pos, 2)
        module(numrows - 1, 0, pos, 3)
        module(0, numcols - 4, pos, 4)
        module(0, numcols - 3, pos, 5)
        module(0, numcols - 2, pos, 6)
        module(0, numcols - 1, pos, 7)
        module(1, numcols - 1, pos, 8)

    def corner3(pos: int) -> None:
        module(numrows - 3, 0, pos, 1)
        module(numrows - 2, 0, pos, 2)
        module(numrows - 1, 0, pos, 3)
        module(0, numcols - 2, pos, 4)
        module(0, numcols - 1, pos, 5)
        module(1, numcols - 1, pos, 6)
        module(2, numcols - 1, pos, 7)
        module(3, numcols - 1, pos, 8)

    def corner4(pos: int) -> None:
        module(numrows - 1, 0, pos, 1)
        module(numrows - 1, numcols - 1, pos, 2)
        module(0, numcols - 3, pos, 3)
        module(0, numcols - 2, pos, 4)
        module(0, numcols - 1, pos, 5)
        module(1, numcols - 3, pos, 6)
        module(1, numcols - 2, pos, 7)
        module(1, numcols - 1, pos, 8)

    pos = 0
    row = 4
    col = 0
    while True:
        if row == numrows and col == 0:
            corner1(pos)
            pos += 1
        if row == numrows - 2 and col == 0 and (numcols % 4) != 0:
            corner2(pos)
            pos += 1
        if row == numrows - 2 and col == 0 and (numcols % 8) == 4:
            corner3(pos)
            pos += 1
        if row == numrows + 4 and col == 2 and (numcols % 8) == 0:
            corner4(pos)
            pos += 1

        while True:
            if row < numrows and col >= 0 and not has_bit(col, row):
                utah(row, col, pos)
                pos += 1
            row -= 2
            col += 2
            if not (row >= 0 and col < numcols):
                break
        row += 1
        col += 3

        while True:
            if row >= 0 and col < numcols and not has_bit(col, row):
                utah(row, col, pos)
                pos += 1
            row += 2
            col -= 2
            if not (row < numrows and col >= 0):
                break
        row += 3
        col += 1

        if not (row < numrows or col < numcols):
            break

    if not has_bit(numcols - 1, numrows - 1):
        set_bit(numcols - 1, numrows - 1, True)
        set_bit(numcols - 2, numrows - 2, True)

    return bits


# ---------------------------------------------------------------------------
# Сборка символа (finder/clock-паттерны)
# ---------------------------------------------------------------------------

def _assemble(bits: list[list[int]], symbol) -> list[list[bool]]:
    _cap, _ec, matrix_w, matrix_h, data_regions, _rsd, _rse = symbol
    h_regions = _horizontal_regions(data_regions)
    v_regions = _vertical_regions(data_regions)
    data_w = h_regions * matrix_w
    data_h = v_regions * matrix_h
    width = data_w + h_regions * 2
    height = data_h + v_regions * 2

    matrix = [[False] * width for _ in range(height)]
    matrix_y = 0

    for y in range(data_h):
        if y % matrix_h == 0:
            for x in range(width):
                matrix[matrix_y][x] = (x % 2) == 0
            matrix_y += 1

        matrix_x = 0
        for x in range(data_w):
            if x % matrix_w == 0:
                matrix[matrix_y][matrix_x] = True
                matrix_x += 1
            matrix[matrix_y][matrix_x] = bool(bits[y][x])
            matrix_x += 1
            if x % matrix_w == matrix_w - 1:
                matrix[matrix_y][matrix_x] = (y % 2) == 0
                matrix_x += 1
        matrix_y += 1

        if y % matrix_h == matrix_h - 1:
            for x in range(width):
                matrix[matrix_y][x] = True
            matrix_y += 1

    return matrix


# ---------------------------------------------------------------------------
# Публичное API
# ---------------------------------------------------------------------------

def build_matrix(data: bytes, gs_as_fnc1: bool = True) -> list[list[bool]]:
    """Закодировать данные и вернуть матрицу модулей (True = чёрный)."""
    data = bytes(data)
    if not data:
        raise DataMatrixError('Пустые данные для DataMatrix')

    codewords = encode_ascii(data, gs_as_fnc1=gs_as_fnc1)
    symbol = _lookup_symbol(len(codewords))
    codewords = _pad(codewords, symbol[0])
    full = encode_ecc200(codewords, symbol)

    numcols = _horizontal_regions(symbol[4]) * symbol[2]
    numrows = _vertical_regions(symbol[4]) * symbol[3]
    bits = place_codewords(full, numcols, numrows)
    return _assemble(bits, symbol)


def data_to_image(
    data: bytes,
    module_px: int = 5,
    quiet_zone: int | None = None,
    gs_as_fnc1: bool = False,
) -> Image.Image:
    """Отрисовать DataMatrix: квадратные модули module_px пикселей.

    quiet_zone — ширина поля покоя в модулях (по умолчанию 1 модуль, как в
    спецификации). gs_as_fnc1 — трактовать GS (0x1D) как FNC1 (см. encode_ascii).
    """
    matrix = build_matrix(data, gs_as_fnc1=gs_as_fnc1)
    n = len(matrix)
    if quiet_zone is None:
        quiet_zone = 1
    side = (n + 2 * quiet_zone) * module_px

    image = Image.new('L', (side, side), 255)
    draw = ImageDraw.Draw(image)
    for y, row_bits in enumerate(matrix):
        y0 = (y + quiet_zone) * module_px
        for x, black in enumerate(row_bits):
            if black:
                x0 = (x + quiet_zone) * module_px
                draw.rectangle(
                    [x0, y0, x0 + module_px - 1, y0 + module_px - 1],
                    fill=0,
                )
    return image
