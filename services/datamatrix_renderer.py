# services/datamatrix_renderer.py
"""Собственный (локальный) отрисовщик кодов DataMatrix (ECC200).

Модуль не обращается ни к Labelary, ни к zplr: матрица символа кодируется
локально (ECC200 через libdmtx/pylibdmtx), а отрисовка — тихая зона, масштаб
модуля и упаковка в ZPL-графику (``^GF``) — выполняется здесь.

Зачем: превью и печать DataMatrix не должны зависеть от внешних сервисов, и
код должен выглядеть как стандартный символ ECC200 (тот же, что рисует
Labelary).

Используется:
  * ``services/zpl_pil_renderer.py`` — для команды ``^BX`` (локальное превью);
  * ``services/preview_renderer.py`` — подменой ``^BX`` на ``^GF`` перед
    Labelary/zplr, чтобы сам символ DataMatrix рисовал наш рендерер.
"""

from __future__ import annotations

import logging
import re
from math import gcd
from typing import List, Sequence, Tuple

from PIL import Image

logger = logging.getLogger(__name__)

# Размер модуля (в пикселях) и тихая зона (в модулях) по умолчанию.
DEFAULT_MODULE_PX = 6
# GS1/ISO 16022 рекомендуют тихую зону не менее 1 модуля; 2 — надёжнее.
DEFAULT_QUIET_ZONE = 2

# Порог бинаризации (libdmtx возвращает чёрно-белое изображение).
_BINARIZE_THRESHOLD = 128


class DataMatrixEncodeError(Exception):
    """Не удалось закодировать/отрисовать DataMatrix."""


def _to_payload(data) -> bytes:
    """Привести входные данные к байтам, сохраняя значения 0..255 (GS и т.п.)."""
    if isinstance(data, bytes):
        return data
    if data is None:
        data = ''
    return str(data).encode('latin-1', errors='replace')


def _runs(seq: Sequence[int]) -> List[int]:
    """Длины чередующихся серий одинаковых значений."""
    if not seq:
        return []
    out: List[int] = []
    cur = seq[0]
    n = 1
    for v in seq[1:]:
        if v == cur:
            n += 1
        else:
            out.append(n)
            cur, n = v, 1
    out.append(n)
    return out


def _binarize(image: Image.Image) -> Image.Image:
    return image.convert('L').point(
        lambda p: 0 if p < _BINARIZE_THRESHOLD else 255
    )


def _dark_bbox(gray: Image.Image):
    """Границы тёмной части (символ без тихой зоны)."""
    # В режиме 'L' фон = 255 (белый): инвертируем, чтобы getbbox взял символ.
    return gray.point(lambda p: 255 - p).getbbox()


def _detect_module_px(gray: Image.Image) -> int:
    """Размер модуля в пикселях — НОД длин серий символа."""
    px = gray.load()
    w, h = gray.size
    factors: List[int] = []
    # Горизонтальные и вертикальные серии внутри символа.
    for y in (0, h // 2, h - 1):
        factors.extend(_runs([1 if px[x, y] < 128 else 0 for x in range(w)]))
    for x in (0, w // 2, w - 1):
        factors.extend(_runs([1 if px[x, y] < 128 else 0 for y in range(h)]))
    factors = [f for f in factors if f > 0]
    if not factors:
        return 1
    module = factors[0]
    for f in factors[1:]:
        module = gcd(module, f)
    return module or 1


def encode_datamatrix(data) -> List[List[int]]:
    """Закодировать данные в матрицу DataMatrix (список строк 0/1).

    Возвращает матрицу символа ECC200 без тихой зоны. Бросает
    :class:`DataMatrixEncodeError`, если pylibdmtx недоступен или данные не
    кодируются.
    """
    try:
        from pylibdmtx.pylibdmtx import encode as _encode
    except Exception as e:  # pragma: no cover - зависит от окружения
        raise DataMatrixEncodeError(
            f'pylibdmtx недоступен, DataMatrix не закодировать: {e}'
        ) from e

    payload = _to_payload(data)
    if not payload:
        raise DataMatrixEncodeError('Пустые данные для DataMatrix')

    try:
        enc = _encode(payload)
    except Exception as e:  # pylibdmtx бросает на некорректных данных
        raise DataMatrixEncodeError(f'DataMatrix не закодирован: {e}') from e

    if enc is None or not getattr(enc, 'width', 0):
        raise DataMatrixEncodeError('DataMatrix не закодирован (пустой результат)')

    gray = _binarize(Image.frombytes('RGB', (enc.width, enc.height), enc.pixels))
    bbox = _dark_bbox(gray)
    if bbox:
        gray = gray.crop(bbox)

    module = _detect_module_px(gray)
    w, h = gray.size
    cols = max(1, round(w / module))
    rows = max(1, round(h / module))

    px = gray.load()
    matrix: List[List[int]] = []
    for r in range(rows):
        y = min(h - 1, r * module + module // 2)
        matrix.append([
            1 if px[min(w - 1, c * module + module // 2), y] < 128 else 0
            for c in range(cols)
        ])

    # Матрица DataMatrix всегда квадратная.
    if rows != cols:
        side = max(rows, cols)
        for r in range(len(matrix)):
            matrix[r] = (matrix[r] + [0] * side)[:side]
        while len(matrix) < side:
            matrix.append([0] * side)

    return matrix


def matrix_size(data) -> Tuple[int, int]:
    """Размер матрицы (столбцы, строки) без тихой зоны."""
    matrix = encode_datamatrix(data)
    return len(matrix[0]), len(matrix)


def _rotate_matrix(matrix: List[List[int]], orient: str) -> List[List[int]]:
    """Поворот матрицы под ориентацию ZPL (N/R/I/B)."""
    orient = (orient or 'N').upper()
    if orient == 'R':      # 90° по часовой
        return [list(row) for row in zip(*matrix[::-1])]
    if orient == 'I':      # 180°
        return [row[::-1] for row in matrix[::-1]]
    if orient == 'B':      # 270° по часовой
        return [list(row) for row in zip(*matrix)][::-1]
    return matrix


def render_datamatrix_image(
    data,
    *,
    module_px: int = DEFAULT_MODULE_PX,
    quiet_zone: int = DEFAULT_QUIET_ZONE,
    orient: str = 'N',
    background: Tuple[int, int, int] = (255, 255, 255),
    foreground: Tuple[int, int, int] = (0, 0, 0),
) -> Image.Image:
    """Отрисовать DataMatrix в PIL-изображение (RGB).

    ``module_px`` — размер модуля в пикселях, ``quiet_zone`` — тихая зона в
    модулях, ``orient`` — ориентация ZPL (N/R/I/B).
    """
    matrix = _rotate_matrix(encode_datamatrix(data), orient)
    rows, cols = len(matrix), len(matrix[0])
    module_px = max(1, int(module_px))
    quiet_zone = max(0, int(quiet_zone))
    side_w = (cols + 2 * quiet_zone) * module_px
    side_h = (rows + 2 * quiet_zone) * module_px

    img = Image.new('RGB', (side_w, side_h), background)
    px = img.load()
    for r in range(rows):
        for c in range(cols):
            if not matrix[r][c]:
                continue
            x0 = (c + quiet_zone) * module_px
            y0 = (r + quiet_zone) * module_px
            for yy in range(y0, y0 + module_px):
                for xx in range(x0, x0 + module_px):
                    px[xx, yy] = foreground
    return img


def render_datamatrix_png(
    data,
    *,
    module_px: int = DEFAULT_MODULE_PX,
    quiet_zone: int = DEFAULT_QUIET_ZONE,
    orient: str = 'N',
) -> bytes:
    """Отрисовать DataMatrix в PNG (bytes)."""
    img = render_datamatrix_image(
        data, module_px=module_px, quiet_zone=quiet_zone, orient=orient,
    )
    import io

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _pack_rows(matrix: List[List[int]], module_px: int) -> Tuple[bytes, int, int]:
    """Упаковать матрицу в 1-битные строки (MSB-first).

    Возвращает (данные, ширина в точках, байт на строку).
    """
    rows, cols = len(matrix), len(matrix[0])
    width_dots = cols * module_px
    bytes_per_row = (width_dots + 7) // 8
    out = bytearray()
    for r in range(rows):
        bits: List[int] = []
        for c in range(cols):
            bits.extend([1 if matrix[r][c] else 0] * module_px)
        while len(bits) % 8:
            bits.append(0)
        while len(bits) < bytes_per_row * 8:
            bits.append(0)
        row_bytes = bytearray()
        for i in range(0, len(bits), 8):
            b = 0
            for bit in bits[i:i + 8]:
                b = (b << 1) | bit
            row_bytes.append(b)
        # Вертикальное масштабирование: модуль — квадрат module_px × module_px,
        # поэтому каждая строка модулей повторяется module_px раз.
        for _ in range(module_px):
            out.extend(row_bytes)
    return bytes(out), width_dots, bytes_per_row


def datamatrix_to_zpl_gfa(
    data,
    *,
    origin_x: int,
    origin_y: int,
    module_dots: int = DEFAULT_MODULE_PX,
    quiet_zone: int = 0,
    orient: str = 'N',
) -> Tuple[str, int, int]:
    """Сгенерировать ZPL-команду ``^FO...^GFA,...`` для DataMatrix.

    Возвращает (строка ZPL, ширина в точках, высота в точках). Тихая зона по
    умолчанию нулевая, чтобы размер и позиция совпадали с ``^BX``.
    """
    matrix = _rotate_matrix(encode_datamatrix(data), orient)
    rows, cols = len(matrix), len(matrix[0])
    module_dots = max(1, int(module_dots))
    quiet_zone = max(0, int(quiet_zone))

    # Добавляем тихую зону в матрицу (по краям — нули).
    if quiet_zone:
        pad = [0] * (cols + 2 * quiet_zone)
        framed = [[0] * (cols + 2 * quiet_zone) for _ in range(quiet_zone)]
        for row in matrix:
            framed.append([0] * quiet_zone + list(row) + [0] * quiet_zone)
        framed.extend([[0] * (cols + 2 * quiet_zone) for _ in range(quiet_zone)])
        matrix = framed

    data_bytes, width_dots, bytes_per_row = _pack_rows(matrix, module_dots)
    height_dots = len(matrix) * module_dots
    total = len(data_bytes)
    # В ASCII-hex (формат A) данные идут сплошной строкой без разделителей:
    # запятые в ^GF разбивают параметры команды и ломают изображение.
    hex_data = ''.join(f'{b:02X}' for b in data_bytes)
    gfa = (
        f'^FO{int(origin_x)},{int(origin_y)}'
        f'^GFA,{total},{total},{bytes_per_row},{hex_data}^FS'
    )
    return gfa, width_dots, height_dots


# ── Подмена ^BX на ^GF (чтобы символ рисовал наш рендерер) ───────────────────

# ^FO x,y ... ^BXo,h,s,... [^FH] ^FD<data>^FS
_DM_FIELD_RE = re.compile(
    r'\^FO\s*(?P<x>\d+)\s*,\s*(?P<y>\d+)(?P<mid>[^\^]*)'
    r'\^BX(?P<bparams>[^\^]*)'
    r'(?P<fh>\^FH)?'
    r'\^FD(?P<data>.*?)\^FS',
    re.DOTALL,
)


def _decode_hex_field(data: str) -> str:
    """Декодирование ``_XX``-последовательностей поля при ``^FH``."""
    out = []
    i = 0
    n = len(data)
    while i < n:
        ch = data[i]
        if (ch == '_' and i + 2 < n
                and data[i + 1] in '0123456789ABCDEFabcdef'
                and data[i + 2] in '0123456789ABCDEFabcdef'):
            out.append(chr(int(data[i + 1:i + 3], 16)))
            i += 3
        else:
            out.append(ch)
            i += 1
    return ''.join(out)


def _module_from_bx_params(bparams: str, default: int = DEFAULT_MODULE_PX) -> int:
    """Достать размер модуля (``h``) из параметров ``^BX``."""
    parts = bparams.split(',')
    if len(parts) >= 2:
        try:
            h = int(parts[1])
            if h > 0:
                return h
        except ValueError:
            pass
    return default


def module_dots_from_zpl(zpl: str, default: int = 4) -> int:
    """Размер модуля DataMatrix (``h`` в ``^BXo,h,s,...``), в точках ZPL.

    Используется, чтобы выгружаемый PDF совпадал по размеру с печатью на
    принтере. Если DataMatrix в ZPL нет — возвращает ``default``.
    """
    match = re.search(r'\^BX([^\^]*)', zpl or '')
    if not match:
        return default
    return _module_from_bx_params(match.group(1), default)


# ── Раскладка DataMatrix для интерактивного редактора шаблонов ───────────────
# Позволяет фронтенду нарисовать «рамку» вокруг DataMatrix в превью и
# перетаскивать её мышью, меняя только координаты ^FO соответствующего поля.

# Размер этикетки по умолчанию (4x6 дюймов), если в ZPL нет ^PW/^LL.
_DEFAULT_LABEL_W_IN = 4.0
_DEFAULT_LABEL_H_IN = 6.0

_PW_RE = re.compile(r'\^PW(\d+)')
_LL_RE = re.compile(r'\^LL(\d+)')
_LH_RE = re.compile(r'\^LH\s*(-?\d+)\s*,\s*(-?\d+)')


def label_size_dots(zpl: str, dpmm: int = 8) -> Tuple[int, int]:
    """Размер этикетки в точках ZPL.

    Берётся из ``^PW``/``^LL`` (они уже в точках); если их нет — 4x6 дюймов
    при заданном ``dpmm`` (по умолчанию 8 точек/мм = 203 dpi, как в превью).
    """
    m = _PW_RE.search(zpl or '')
    w = int(m.group(1)) if m else int(round(_DEFAULT_LABEL_W_IN * dpmm * 25.4))
    m = _LL_RE.search(zpl or '')
    h = int(m.group(1)) if m else int(round(_DEFAULT_LABEL_H_IN * dpmm * 25.4))
    return w, h


def label_home_dots(zpl: str) -> Tuple[int, int]:
    """Смещение начала координат ``^LH`` (по умолчанию 0,0)."""
    m = _LH_RE.search(zpl or '')
    if not m:
        return 0, 0
    return int(m.group(1)), int(m.group(2))


def datamatrix_size_dots(data, module_dots: int, orient: str = 'N') -> Tuple[int, int]:
    """Размер символа DataMatrix в точках ZPL (без тихой зоны).

    Ширина/высота = число модулей (с учётом ориентации) × размер модуля.
    """
    matrix = _rotate_matrix(encode_datamatrix(data), orient)
    rows, cols = len(matrix), len(matrix[0])
    module = max(1, int(module_dots))
    return cols * module, rows * module


def datamatrix_fields_layout(
    zpl: str,
    *,
    sample_data: str = '',
    default_module: int = DEFAULT_MODULE_PX,
) -> dict:
    """Раскладка полей DataMatrix в ZPL для визуального редактора.

    Возвращает словарь::

        {
          'label_w': <ширина этикетки в точках>,
          'label_h': <высота этикетки в точках>,
          'lh_x': <^LH x>, 'lh_y': <^LH y>,
          'fields': [
            {'index': 0, 'x': 30, 'y': 30, 'w': 50, 'h': 50,
             'module': 5, 'orient': 'N'},
            ...
          ],
        }

    Координаты ``x``/``y`` — значения ``^FO`` поля (без ``^LH``), ``w``/``h`` —
    размер символа в точках. Плейсхолдер ``{datamatrix}`` (а также любое
    выражение со ``{``) заменяется на ``sample_data``, чтобы размер совпал с
    тем, что реально рисуется в превью.
    """
    lh_x, lh_y = label_home_dots(zpl)
    label_w, label_h = label_size_dots(zpl)

    fields: List[dict] = []
    for idx, m in enumerate(_DM_FIELD_RE.finditer(zpl or '')):
        bparams = m.group('bparams') or ''
        orient = bparams[0].upper() if bparams and bparams[0].upper() in 'NRIB' else 'N'
        module = _module_from_bx_params(bparams, default_module)
        data = m.group('data') or ''
        if m.group('fh'):
            data = _decode_hex_field(data)
        if (not data or '{' in data) and sample_data:
            data = sample_data
        try:
            w, h = datamatrix_size_dots(data, module, orient)
        except DataMatrixEncodeError:
            # Данные не кодируются — даём запасной квадрат, чтобы рамку можно
            # было перетаскивать (координаты всё равно верные).
            w = h = module * 16
        fields.append({
            'index': idx,
            'x': int(m.group('x')),
            'y': int(m.group('y')),
            'w': w,
            'h': h,
            'module': module,
            'orient': orient,
        })

    return {
        'label_w': label_w,
        'label_h': label_h,
        'lh_x': lh_x,
        'lh_y': lh_y,
        'fields': fields,
    }


def replace_datamatrix_with_graphics(zpl: str) -> Tuple[str, int]:
    """Заменить поля ``^BX`` (DataMatrix) на ``^GF`` нашего рендерера.

    Возвращает (преобразованный ZPL, число замен). Если DataMatrix-полей нет
    или символы не кодируются, соответствующие поля оставляются без изменений.
    """
    replaced = 0

    def _sub(match: re.Match) -> str:
        nonlocal replaced
        x = int(match.group('x'))
        y = int(match.group('y'))
        bparams = match.group('bparams') or ''
        orient = bparams[0] if bparams and bparams[0].upper() in 'NRIB' else 'N'
        module = _module_from_bx_params(bparams)
        data = match.group('data') or ''
        if match.group('fh'):
            data = _decode_hex_field(data)
        if not data:
            return match.group(0)
        try:
            gfa, _, _ = datamatrix_to_zpl_gfa(
                data, origin_x=x, origin_y=y,
                module_dots=module, quiet_zone=0, orient=orient,
            )
        except DataMatrixEncodeError as e:
            logger.warning('DataMatrix (^BX) не отрисован локально: %s', e)
            return match.group(0)
        replaced += 1
        return gfa

    return _DM_FIELD_RE.sub(_sub, zpl), replaced
