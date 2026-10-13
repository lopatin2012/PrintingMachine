# conftest.py
"""Общий conftest pytest: возвращает корень проекта в ``sys.path``.

Тесты лежат в ``tests/<пакет>/test_*.py`` и импортируют модули приложения
(``from services... import ...``, ``from main import app`` и т.п.). pytest в
режиме prepend добавляет в ``sys.path`` каталог самого теста, а не корень
проекта, поэтому без этого файла импорты ``services``/``helpers``/``routers``
не находились бы при запуске просто ``pytest`` (при ``python -m pytest`` корень
и так попадает в ``sys.path`` как cwd). Пакеты приложения — namespace-пакеты
(``__init__.py`` нет), им для импорта достаточно корня проекта в ``sys.path``.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
