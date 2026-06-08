from pathlib import Path
import os

CONFIG_BASE_DIR = Path(__file__).resolve().parent.parent

ZEBRASH_BINARY = os.getenv(
    'ZEBRASH_BINARY',
    str(CONFIG_BASE_DIR / 'bin' / 'zebrash-render')
)

ZPL_RENDER_DEFAULTS = {
    'width_mm': 101.6, # 4dm
    'height_mm': 152.4, # 6dm
    'dpmm': 8, # 203 DPI
    'timeout_sec': 10,
}