# services/zpl_pil_renderer.py
"""Локальный рендер ZPL → PNG на чистом Python (PIL + python-barcode + pylibdmtx).

Офлайн-аналог Labelary без внешних бинарников. Покрывает команды, которые
реально используются в шаблонах этикеток:

    ^XA/^XZ            — начало/конец этикетки
    ^PW/^LL/^LH        — ширина/длина этикетки, сдвиг начала координат
    ^PO/^FW            — ориентация этикетки/полей (N/R/I/B)
    ^FO/^FT/^FD/^FS    — поля (FO — верхний левый угол, FT — базисная линия)
    ^A0..^A9/^CF/^FB   — шрифты, блоки текста с переносом
    ^FH                — HEX-данные поля (_XX)
    ^BY/^BC            — Code128 / GS1-128 (FNC1, режимы UCC)
    ^B3                — Code39
    ^B2                — Interleaved 2 of 5
    ^B7/^B8            — EAN-13 / EAN-8
    ^BX                — DataMatrix (pylibdmtx)
    ^GB                — прямоугольники / линии
    ^GF                — растровые изображения (только заглушка)

Неизвестные команды игнорируются. Неподдерживаемые штрихкоды рисуются как
плейсхолдер-область с подписью.
"""

from __future__ import annotations

import io
import logging
import os

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

from barcode.codex import Code128, Gs1_128  # noqa: E402
from barcode.charsets import code128 as _code128  # noqa: E402

# Собственный движок DataMatrix ECC200 (кодирование + модули) — без
# pylibdmtx/libdmtx и внешних сервисов.
from services.datamatrix_renderer import DataMatrixError, build_matrix  # noqa: E402

HAS_DMTX = True  # собственный движок доступен всегда

DEFAULT_DPMM = 8  # 203 dpi
DEFAULT_WIDTH_MM = 101.6
DEFAULT_HEIGHT_MM = 152.4

# Ориентации ZPL → угол поворота по часовой стрелке (градусы).
ORIENT_DEG = {'N': 0, 'R': 90, 'I': 180, 'B': 270}

# Максимальный размер итогового PNG по длинной стороне (пикселей).
MAX_CANVAS_PX = 2400

_FONT_CACHE: dict[tuple[int, bool, bool], ImageFont.ImageFont] = {}

# Кандидаты шрифтов: сначала системные (Windows), затем DejaVu/Liberation (Linux).
_FONT_CANDIDATES = {
    'default': [
        r'C:\Windows\Fonts\arial.ttf',
        r'C:\Windows\Fonts\arialbd.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    ],
    'mono': [
        r'C:\Windows\Fonts\cour.ttf',
        r'C:\Windows\Fonts\courbd.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf',
    ],
}


def _get_font(size: int, mono: bool = False) -> ImageFont.ImageFont:
    """Truetype-шрифт с кэшем. Размер — в пикселях (точках ZPL × масштаб)."""
    key = (size, mono)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    font = None
    for path in _FONT_CANDIDATES['mono' if mono else 'default']:
        try:
            if os.path.exists(path):
                font = ImageFont.truetype(path, size)
                break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


def _parse_int(value: str, default: float = 0) -> float:
    """Парс целого из параметра ZPL (может быть отрицательным/пустым)."""
    value = (value or '').strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _split_params(params: str) -> list[str]:
    return [p.strip() for p in (params or '').split(',')]


def _decode_hex_field(data: str) -> str:
    """Декодирование `_XX`-последовательностей поля ^FH."""
    out = []
    i = 0
    n = len(data)
    while i < n:
        ch = data[i]
        if ch == '_' and i + 2 < n and data[i + 1] in '0123456789ABCDEFabcdef' \
                and data[i + 2] in '0123456789ABCDEFabcdef':
            out.append(chr(int(data[i + 1:i + 3], 16)))
            i += 3
        else:
            out.append(ch)
            i += 1
    return ''.join(out)


def _unescape_fd(data: str) -> str:
    """Разворачивает спец-символы ^FD: \\& — перевод строки, \\^ — '^', \\\\ — '\\'."""
    return (
        data.replace('\\&', '\n')
        .replace('\\^', '^')
        .replace('\\\\', '\\')
    )


def _code128_bars(data: str, gs1: bool = False) -> str:
    """Битовая строка (1 — штрих, 0 — пробел) штрихкода Code128/GS1-128."""
    prepared = data.replace('\x1d', '\xf1')  # GS-разделитель → FNC1
    if gs1:
        # Gs1_128: Start C + FNC1 + пары цифр (каноническое GS1-128-кодирование).
        code = Gs1_128(prepared)
    else:
        code = Code128(prepared)
    encoded = code.encoded  # символы без контрольного
    encoded.append(
        sum([encoded[0]] + [i * v for i, v in enumerate(encoded[1:], start=1)]) % 103
    )
    return ''.join(_code128.CODES[n] for n in encoded) + _code128.STOP + '11'


def _hri_text(data: str, gs1: bool = False) -> str:
    """Человекочитаемая подпись штрихкода. GS1-128: AI в скобках."""
    if gs1:
        parts = data.split('\x1d')
        out = []
        for part in parts:
            if len(part) >= 2 and part[:2].isdigit():
                out.append(f'({part[:2]}){part[2:]}')
            else:
                out.append(part)
        return ' '.join(out)
    return data.replace('\x1d', ' ')


class _ZplRenderer:
    """Построчный интерпретатор ZPL с отрисовкой на канве PIL."""

    def __init__(
        self,
        zpl_code: str,
        width_mm: float | None = None,
        height_mm: float | None = None,
        dpmm: int = DEFAULT_DPMM,
        scale: int = 2,
    ):
        self.zpl = zpl_code
        self.dpmm = dpmm
        self.scale = scale

        # Размеры этикетки в точках (из ^PW/^LL, иначе из мм).
        self.width_dots = int((width_mm or DEFAULT_WIDTH_MM) * dpmm)
        self.height_dots = int((height_mm or DEFAULT_HEIGHT_MM) * dpmm)

        self.px_w = self.width_dots * scale
        self.px_h = self.height_dots * scale

        # Состояние полей.
        self.origin_x = 0.0
        self.origin_y = 0.0
        self.origin_type = 'FO'  # FO — верхний левый угол, FT — базисная линия
        self.label_home_x = 0.0
        self.label_home_y = 0.0
        self.label_inverted = False  # ^POI — поворот всей этикетки на 180°

        # Текущий шрифт.
        self.font_id = '0'
        self.font_orient = 'N'
        self.font_height = 40.0
        self.font_width = 0.0
        self.field_orient = 'N'  # ^FW

        # Штрихкод по умолчанию (^BY).
        self.barcode_mod = 2.0
        self.barcode_height = 100.0
        self.barcode_ratio = 3.0

        # Поле-штрихкод, ожидающее данных из ^FD.
        self.pending_barcode: tuple[str, list[str]] | None = None
        self.hex_mode = False
        self.field_block: list[float] | None = None

        self.image = Image.new(
            'RGB', (self.px_w, self.px_h), 'white'
        )
        self.draw = ImageDraw.Draw(self.image)

    # ------------------------------------------------------------------ API

    def render(self) -> bytes:
        for chunk in self.zpl.split('^'):
            if not chunk:
                continue
            try:
                self._process_chunk(chunk)
            except Exception as e:
                logger.warning('Не удалось обработать фрагмент ZPL %r: %s', chunk[:40], e)
        if self.label_inverted:
            self.image = self.image.rotate(180)
        buf = io.BytesIO()
        self.image.save(buf, format='PNG')
        return buf.getvalue()

    # ------------------------------------------------------------- парсинг

    def _process_chunk(self, chunk: str) -> None:
        # Штрихкоды вида ^BC/^BX/^B3/^B2/^B7/^B8/^BQ: 'B' + тип + ориентация.
        if chunk[0] == 'B' and len(chunk) >= 2 and chunk[1] in 'CX2378QI':
            btype = chunk[1]
            orient = chunk[2] if len(chunk) > 2 and chunk[2] in ORIENT_DEG else 'N'
            params = chunk[3:]
            self.pending_barcode = (btype, [orient] + _split_params(params))
            return

        # Шрифт вида ^A0N,высота,ширина / ^A0,высота,ширина.
        if chunk[0] == 'A' and len(chunk) >= 2 and chunk[1].isdigit():
            orient = chunk[2] if len(chunk) > 2 and chunk[2] in ORIENT_DEG else 'N'
            params = _split_params(chunk[3:])
            self.font_id = chunk[1]
            self.font_orient = orient
            if len(params) >= 1:
                self.font_height = _parse_int(params[0], self.font_height)
            if len(params) >= 2:
                self.font_width = _parse_int(params[1], self.font_width)
            return

        cmd = chunk[:2]
        params = chunk[2:]
        handler = getattr(self, f'_cmd_{cmd.lower()}', None)
        if handler is not None:
            handler(params)

    # ------------------------------------------------------------- команды

    def _cmd_pw(self, params: str) -> None:
        w = _parse_int(params, 0)
        if w > 0:
            self.width_dots = int(w)
            self.px_w = int(w) * self.scale
            self.image = self.image.resize((self.px_w, self.px_h), Image.NEAREST)
            self.draw = ImageDraw.Draw(self.image)

    def _cmd_ll(self, params: str) -> None:
        h = _parse_int(params, 0)
        if h > 0:
            self.height_dots = int(h)
            self.px_h = int(h) * self.scale
            self.image = self.image.resize((self.px_w, self.px_h), Image.NEAREST)
            self.draw = ImageDraw.Draw(self.image)

    def _cmd_lh(self, params: str) -> None:
        p = _split_params(params)
        if p:
            self.label_home_x = _parse_int(p[0], 0)
        if len(p) > 1:
            self.label_home_y = _parse_int(p[1], 0)

    def _cmd_po(self, params: str) -> None:
        self.label_inverted = (params or '').strip().upper() == 'I'

    def _cmd_fo(self, params: str) -> None:
        p = _split_params(params)
        if len(p) >= 2:
            self.origin_x = _parse_int(p[0], 0)
            self.origin_y = _parse_int(p[1], 0)
            self.origin_type = 'FO'

    def _cmd_ft(self, params: str) -> None:
        p = _split_params(params)
        if len(p) >= 2:
            self.origin_x = _parse_int(p[0], 0)
            self.origin_y = _parse_int(p[1], 0)
            self.origin_type = 'FT'

    def _cmd_fw(self, params: str) -> None:
        o = (params or '').strip().upper()
        if o in ORIENT_DEG:
            self.field_orient = o

    def _cmd_cf(self, params: str) -> None:
        # ^CFA,высота,ширина — смена шрифта по умолчанию.
        p = _split_params(params)
        if p and p[0]:
            self.font_id = p[0][0] if p[0][0].isdigit() else '0'
            if len(p[0]) > 1 and p[0][1] in ORIENT_DEG:
                self.font_orient = p[0][1]
        if len(p) >= 2:
            self.font_height = _parse_int(p[1], self.font_height)
        if len(p) >= 3:
            self.font_width = _parse_int(p[2], self.font_width)

    def _cmd_by(self, params: str) -> None:
        p = _split_params(params)
        if len(p) >= 1:
            self.barcode_mod = max(1.0, _parse_int(p[0], self.barcode_mod))
        if len(p) >= 2:
            self.barcode_ratio = _parse_int(p[1], self.barcode_ratio) or 3.0
        if len(p) >= 3:
            self.barcode_height = _parse_int(p[2], self.barcode_height)

    def _cmd_fb(self, params: str) -> None:
        self.field_block = [_parse_int(x, 0) for x in _split_params(params)]

    def _cmd_fh(self, params: str) -> None:
        self.hex_mode = True

    def _cmd_fd(self, params: str) -> None:
        data = params
        if self.hex_mode:
            data = _decode_hex_field(data)
            self.hex_mode = False
        data = _unescape_fd(data)
        if self.pending_barcode is not None:
            btype, bparams = self.pending_barcode
            self.pending_barcode = None
            self._draw_barcode(btype, bparams, data)
        else:
            self._draw_text(data)

    def _cmd_fs(self, params: str) -> None:
        self.pending_barcode = None
        self.field_block = None

    def _cmd_gb(self, params: str) -> None:
        p = _split_params(params)
        if len(p) < 2:
            return
        w = abs(_parse_int(p[0], 0))
        h = abs(_parse_int(p[1], 0))
        t = max(1, _parse_int(p[2], 1))
        color = (p[3] or '').upper() if len(p) > 3 else 'B'
        x = (self.origin_x + self.label_home_x) * self.scale
        y = (self.origin_y + self.label_home_y) * self.scale
        fill = 'black' if color in ('B', '1') else 'white'
        outline = fill
        self.draw.rectangle(
            [x, y, x + w * self.scale, y + h * self.scale],
            outline=outline, fill=None, width=int(t * self.scale),
        )

    # ------------------------------------------------------------- текст

    def _draw_text(self, data: str) -> None:
        if not data:
            return
        lines = data.split('\n')
        orient_deg = (ORIENT_DEG.get(self.field_orient, 0)
                      + ORIENT_DEG.get(self.font_orient, 0)) % 360
        font_px = max(8, int(self.font_height * self.scale))
        font = _get_font(font_px, mono=self.font_id == '1')

        # Рисуем каждую строку отдельно (с учётом ^FB переноса).
        block_w = (self.field_block[0] if self.field_block else 0) * self.scale
        wrapped: list[str] = []
        for line in lines:
            if block_w and font is not None:
                wrapped.extend(_wrap_text(self.draw, line, font, block_w))
            else:
                wrapped.append(line)

        ascent, descent = font.getmetrics()
        line_px = ascent + descent
        text_h = line_px * len(wrapped)
        text_w = max((self.draw.textbbox((0, 0), ln, font=font)[2] for ln in wrapped),
                     default=0)

        # Сжатие по ширине ^A0N,h,w (w < h — «узкий» шрифт).
        if self.font_width and self.font_height and self.font_width < self.font_height:
            target_w = int(text_w * self.font_width / self.font_height)
            if target_w > 0 and target_w < text_w:
                text_h = int(text_h * target_w / text_w) if text_w else text_h

        tmp = Image.new('RGBA', (max(1, text_w), max(1, text_h)), (255, 255, 255, 0))
        tdraw = ImageDraw.Draw(tmp)
        for i, line in enumerate(wrapped):
            tdraw.text((0, i * line_px), line, font=font, fill='black')

        tmp = self._apply_width_scale(tmp, self.font_width, self.font_height)

        if orient_deg:
            tmp = tmp.rotate(-orient_deg, expand=True)

        x = (self.origin_x + self.label_home_x) * self.scale
        y = (self.origin_y + self.label_home_y) * self.scale
        if self.origin_type == 'FT':
            y -= ascent * self.scale  # ^FT: y — это базисная линия
        self.image.paste(tmp, (int(x), int(y)), tmp)

    def _apply_width_scale(self, tmp: Image.Image, font_width: float, font_height: float) -> Image.Image:
        if not font_width or not font_height or font_width >= font_height:
            return tmp
        w = max(1, int(tmp.width * font_width / font_height))
        h = max(1, int(tmp.height * font_width / font_height))
        return tmp.resize((w, h), Image.LANCZOS)

    # ----------------------------------------------------------- штрихкоды

    def _draw_barcode(self, btype: str, bparams: list[str], data: str) -> None:
        orient = bparams[0] if bparams and bparams[0] in ORIENT_DEG else 'N'
        rest = bparams[1:] if bparams else []

        if btype == 'B':
            return  # ^FB уже обрабатывается как текст

        if btype == 'X':  # DataMatrix
            self._draw_datamatrix(orient, rest, data)
            return

        handler = getattr(self, f'_barcode_{btype.lower()}', None)
        if handler is None:
            self._draw_placeholder_barcode(data, rest)
            return
        try:
            handler(orient, rest, data)
        except Exception as e:
            logger.warning('Штрихкод %s (%r): %s — рисуем плейсхолдер', btype, data[:20], e)
            self._draw_placeholder_barcode(data, rest)

    def _barcode_c(self, orient: str, rest: list[str], data: str) -> None:
        height = _parse_int(rest[0], self.barcode_height) if rest else self.barcode_height
        hri_yn = (rest[1] or '').upper() if len(rest) > 1 else 'Y'
        hri_above = (rest[2] or '').upper() == 'Y' if len(rest) > 2 else False
        ucc = (rest[3] or '').upper() if len(rest) > 3 else 'N'
        mode = (rest[4] or '').upper() if len(rest) > 4 else 'N'
        gs1 = mode in ('A', 'U', 'D') or ucc == 'Y' or '\x1d' in data
        self._draw_linear_barcode(
            orient, data, _code128_bars(data, gs1),
            self.barcode_mod, height,
            hri=hri_yn != 'N', hri_above=hri_above, hri_text=_hri_text(data, gs1),
        )

    def _barcode_3(self, orient: str, rest: list[str], data: str) -> None:
        height = _parse_int(rest[0], self.barcode_height) if rest else self.barcode_height
        hri_yn = (rest[1] or '').upper() if len(rest) > 1 else 'Y'
        from barcode.codex import Code39

        code = Code39(data)
        bits = code.build()[0]
        self._draw_linear_barcode(
            orient, data, bits, self.barcode_mod, height,
            hri=hri_yn != 'N',
        )

    def _barcode_2(self, orient: str, rest: list[str], data: str) -> None:
        height = _parse_int(rest[0], self.barcode_height) if rest else self.barcode_height
        hri_yn = (rest[1] or '').upper() if len(rest) > 1 else 'Y'
        if len(data) % 2:
            data = '0' + data  # Interleaved 2 of 5 требует чётное число цифр
        from barcode.itf import ITF

        bits = ITF(data).build()[0]
        self._draw_linear_barcode(
            orient, data, bits, self.barcode_mod, height,
            hri=hri_yn != 'N',
        )

    def _barcode_7(self, orient: str, rest: list[str], data: str) -> None:
        height = _parse_int(rest[0], self.barcode_height) if rest else self.barcode_height
        hri_yn = (rest[1] or '').upper() if len(rest) > 1 else 'Y'
        from barcode.ean import EAN13

        code = EAN13(data[:13].ljust(13, '0'))
        self._draw_linear_barcode(
            orient, data, code.build()[0], self.barcode_mod, height,
            hri=hri_yn != 'N',
        )

    def _barcode_8(self, orient: str, rest: list[str], data: str) -> None:
        height = _parse_int(rest[0], self.barcode_height) if rest else self.barcode_height
        hri_yn = (rest[1] or '').upper() if len(rest) > 1 else 'Y'
        from barcode.ean import EAN8

        code = EAN8(data[:8].ljust(8, '0'))
        self._draw_linear_barcode(
            orient, data, code.build()[0], self.barcode_mod, height,
            hri=hri_yn != 'N',
        )

    def _draw_linear_barcode(
        self,
        orient: str,
        data: str,
        bits: str,
        module: float,
        height: float,
        hri: bool = True,
        hri_above: bool = False,
        hri_text: str | None = None,
    ) -> None:
        module_px = max(1, int(module * self.scale))
        height_px = max(4, int(height * self.scale))
        width_px = len(bits) * module_px

        tmp = Image.new('RGBA', (width_px, height_px), (255, 255, 255, 0))
        tdraw = ImageDraw.Draw(tmp)
        for idx, bit in enumerate(bits):
            if bit == '1':
                x0 = idx * module_px
                tdraw.rectangle([x0, 0, x0 + module_px, height_px], fill='black')

        # Человекочитаемая подпись.
        font_px = max(10, int(12 * self.scale))
        font = _get_font(font_px, mono=True)
        asc, desc = font.getmetrics()
        label = hri_text if hri_text is not None else data.replace('\x1d', ' ')
        if hri and label:
            label_w = tdraw.textlength(label, font=font)
            lbl = Image.new('RGBA', (max(1, int(label_w) + 4), asc + desc), (255, 255, 255, 0))
            ImageDraw.Draw(lbl).text((0, 0), label, font=font, fill='black')
            bar_w = width_px
            lbl_w = lbl.width
            if lbl_w > bar_w:
                tmp = Image.new('RGBA', (lbl_w, height_px + lbl.height), (255, 255, 255, 0))
                tdraw = ImageDraw.Draw(tmp)
                for idx, bit in enumerate(bits):
                    if bit == '1':
                        x0 = idx * module_px
                        tdraw.rectangle([x0, 0, x0 + module_px, height_px], fill='black')
                if hri_above:
                    tmp.paste(lbl, (0, 0), lbl)
                else:
                    tmp.paste(lbl, (0, height_px), lbl)
            else:
                x = (width_px - lbl_w) // 2
                if hri_above:
                    tmp.paste(lbl, (x, 0), lbl)
                else:
                    tmp.paste(lbl, (x, height_px), lbl)

        deg = ORIENT_DEG.get(orient, 0)
        if deg:
            tmp = tmp.rotate(-deg, expand=True)

        x = (self.origin_x + self.label_home_x) * self.scale
        y = (self.origin_y + self.label_home_y) * self.scale
        self.image.paste(tmp, (int(x), int(y)), tmp)

    @staticmethod
    def _render_datamatrix_image(data: str, cell_px: int) -> Image.Image | None:
        """Отрисовать DataMatrix собственным движком (ECC200).

        Возвращает RGBA-изображение с квадратными модулями `cell_px` пикселей
        или None, если закодировать не удалось.
        """
        try:
            payload = data.encode('utf-8')
            matrix = build_matrix(payload, gs_as_fnc1=False)
        except (DataMatrixError, UnicodeEncodeError, ValueError) as e:
            logger.warning('DataMatrix не закодирован (%s) — плейсхолдер', e)
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning('DataMatrix: непредвиденная ошибка (%s) — плейсхолдер', e)
            return None

        n = len(matrix)
        side = n * cell_px
        img = Image.new('RGBA', (side, side), (255, 255, 255, 0))
        draw = ImageDraw.Draw(img)
        for y, row_bits in enumerate(matrix):
            y0 = y * cell_px
            for x, black in enumerate(row_bits):
                if black:
                    x0 = x * cell_px
                    draw.rectangle(
                        [x0, y0, x0 + cell_px - 1, y0 + cell_px - 1],
                        fill='black',
                    )
        return img

    def _draw_datamatrix(self, orient: str, rest: list[str], data: str) -> None:
        cell_dots = _parse_int(rest[0], 6) if rest else 6
        if cell_dots <= 4:  # плотность 0..3 вместо размера ячейки
            cell_dots = 6
        cell_px = max(1, int(cell_dots * self.scale))

        tmp = self._render_datamatrix_image(data, cell_px) if data else None

        if tmp is None:
            # Плейсхолдер: квадрат с подписью.
            side = max(8, cell_px * 10)
            tmp = Image.new('RGBA', (side, side), (255, 255, 255, 0))
            tdraw = ImageDraw.Draw(tmp)
            tdraw.rectangle([0, 0, side - 1, side - 1], outline='black', width=2)
            font = _get_font(max(10, int(10 * self.scale)))
            tdraw.text((side // 2, side // 2), 'DM', font=font, fill='black',
                       anchor='mm')

        deg = ORIENT_DEG.get(orient, 0)
        if deg:
            tmp = tmp.rotate(-deg, expand=True)

        x = (self.origin_x + self.label_home_x) * self.scale
        y = (self.origin_y + self.label_home_y) * self.scale
        self.image.paste(tmp, (int(x), int(y)), tmp)

    def _draw_placeholder_barcode(self, data: str, rest: list[str]) -> None:
        height = _parse_int(rest[0], self.barcode_height) if rest else self.barcode_height
        w = max(80, int(120 * self.scale))
        h = max(10, int(height * self.scale))
        tmp = Image.new('RGBA', (w, h), (255, 255, 255, 0))
        tdraw = ImageDraw.Draw(tmp)
        tdraw.rectangle([0, 0, w - 1, h - 1], outline='black', width=2)
        font = _get_font(max(10, int(10 * self.scale)))
        tdraw.text((w // 2, h // 2), data[:20], font=font, fill='black', anchor='mm')
        x = (self.origin_x + self.label_home_x) * self.scale
        y = (self.origin_y + self.label_home_y) * self.scale
        self.image.paste(tmp, (int(x), int(y)), tmp)


def _wrap_text(draw: ImageDraw.ImageDraw, line: str, font, max_width: int) -> list[str]:
    """Перенос длинной строки по словам в пределах max_width."""
    if draw.textlength(line, font=font) <= max_width:
        return [line]
    words = line.split(' ')
    result: list[str] = []
    cur = ''
    for word in words:
        candidate = f'{cur} {word}'.strip()
        if draw.textlength(candidate, font=font) <= max_width:
            cur = candidate
        else:
            if cur:
                result.append(cur)
            cur = word
    if cur:
        result.append(cur)
    return result


def render_zpl_to_png(
    zpl_code: str,
    width_mm: float | None = None,
    height_mm: float | None = None,
    dpmm: int = DEFAULT_DPMM,
) -> bytes:
    """Рендер ZPL-этикетки в PNG (локально, без внешних сервисов/бинарников)."""
    renderer = _ZplRenderer(zpl_code, width_mm, height_mm, dpmm)
    return renderer.render()