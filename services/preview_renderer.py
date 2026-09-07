# services/preview_renderer.py
"""Цепочка рендера PNG-превью этикетки: Labelary -> zplr -> PIL.

Основной путь — внешний сервис Labelary (даёт тот же вид, что был раньше).
Если Labelary недоступен — локальный рендер через zplr (Node-бридж, геометрия
как у Labelary, кириллица жирным шрифтом). Если и zplr недоступен —
гарантированный фолбэк на локальный PIL-рендерер.

Каждый шаг создаёт PNG; модуль возвращает (bytes, engine), где engine —
'labelary' | 'zplr' | 'pil', и в HTTP-ответ отдаётся как X-Render-Engine.

zplr-фолбэк опционален: требует node + npm-пакеты zplr и skia-canvas
(см. package.json в корне). Без них тихо переходим на Pillow.
"""

import logging
import os
import re
import shutil
import subprocess

import httpx

from config import CONFIG_BASE_DIR as BASE_DIR
from services.zpl_pil_renderer import render_zpl_to_png

logger = logging.getLogger(__name__)

# Ссылка на внешний рендер-сервис (как исторический Labelary).
LABELARY_BASE = "https://api.labelary.com/v1/printers/{dpmm}dpmm/labels/{w}x{h}/{index}/"

# Пути к Node-бриджу zplr (корень проекта).
ZPLR_NODE_SCRIPT = BASE_DIR / "zplr_preview_server.mjs"
_ZPLR_NODE_MODULES = BASE_DIR / "node_modules"
# Масштаб текста для zplr-фолбэка (подобран по эталону Labelary).
ZPLR_TEXT_SCALE = float(os.getenv("ZPLR_TEXT_SCALE", "0.66"))
ZPLR_FONT = os.getenv(
    "ZPLR_FONT",
    str(BASE_DIR / "static" / "fonts" / "RobotoCondensed-Bold.ttf"),
)

# Дефолтный размер этикетки (дюймы), если в ZPL нет ^PW/^LL.
_DEFAULT_W_IN = 4.0
_DEFAULT_H_IN = 6.0


class PreviewRenderError(Exception):
    """Ошибка рендера превью — пробуем следующий движок в цепочке."""


def _dots_to_inches(dpmm: int, dots: int) -> float:
    return dots / dpmm / 25.4


def parse_label_size_inches(zpl: str, dpmm: int) -> tuple[float, float]:
    """Размер этикетки в дюймах из ^PW/^LL (иначе дефолт 4x6)."""
    pw = re.search(r"\^PW(\d+)", zpl)
    ll = re.search(r"\^LL(\d+)", zpl)
    w = round(_dots_to_inches(dpmm, int(pw.group(1))), 3) if pw else _DEFAULT_W_IN
    h = round(_dots_to_inches(dpmm, int(ll.group(1))), 3) if ll else _DEFAULT_H_IN
    return w, h


def render_via_labelary(zpl: str, dpmm: int = 8) -> bytes:
    """Рендер PNG через Labelary. Бросает PreviewRenderError при сбое."""
    w_in, h_in = parse_label_size_inches(zpl, dpmm)
    url = LABELARY_BASE.format(dpmm=dpmm, w=w_in, h=h_in, index=0)
    try:
        response = httpx.post(
            url,
            content=zpl.encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=40.0,
        )
        response.raise_for_status()
    except Exception as e:  # noqa: BLE001 - любой сбой сети/HTTP -> след. движок
        raise PreviewRenderError(f"Labelary недоступен: {e}") from e
    if not response.content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise PreviewRenderError("Labelary вернул не PNG")
    return response.content


def _zplr_available() -> bool:
    if shutil.which("node") is None:
        return False
    if not ZPLR_NODE_SCRIPT.exists():
        return False
    for pkg in ("zplr", "skia-canvas"):
        if not (_ZPLR_NODE_MODULES / pkg).exists():
            return False
    return True


def render_via_zplr(zpl: str, dpmm: int = 8) -> bytes:
    """Локальный рендер PNG через zplr (Node). Бросает PreviewRenderError."""
    if not _zplr_available():
        raise PreviewRenderError("zplr (node) не доступен")
    env = os.environ.copy()
    env["ZPLR_DPMM"] = str(dpmm)
    env["ZPLR_TEXT_SCALE"] = str(ZPLR_TEXT_SCALE)
    env["ZPLR_FONT"] = ZPLR_FONT
    try:
        result = subprocess.run(
            ["node", str(ZPLR_NODE_SCRIPT)],
            input=zpl.encode("utf-8"),
            capture_output=True,
            timeout=60.0,
            env=env,
            cwd=str(BASE_DIR),
        )
    except Exception as e:  # noqa: BLE001
        raise PreviewRenderError(f"zplr (node) не запустился: {e}") from e
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or b"").decode("utf-8", "replace")
        raise PreviewRenderError(f"zplr (node) ошибка: {detail[-300:]}")
    if not result.stdout.startswith(b"\x89PNG\r\n\x1a\n"):
        raise PreviewRenderError("zplr (node) вернул не PNG")
    return result.stdout


def render_preview_png(zpl: str, dpmm: int = 8) -> tuple[bytes, str]:
    """Цепочка рендера. Возвращает (png_bytes, engine)."""
    for engine, fn in (
        ("labelary", lambda: render_via_labelary(zpl, dpmm)),
        ("zplr", lambda: render_via_zplr(zpl, dpmm)),
        ("pil", lambda: render_zpl_to_png(zpl)),
    ):
        try:
            data = fn()
        except Exception as e:  # noqa: BLE001
            logger.warning("Рендер превью движком %s не удался: %s", engine, e)
            continue
        logger.info("Превью отрендерено движком %s (%d bytes)", engine, len(data))
        return data, engine
    raise PreviewRenderError("Не удалось отрендерить превью ни одним движком")
