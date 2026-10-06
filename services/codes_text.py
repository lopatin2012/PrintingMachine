# services/codes_text.py
"""Формирование текстового файла с DataMatrix-кодами.

Один код на строку — файл удобно скопировать или загрузить во внешнюю
систему. Используется на странице печати: при запуске печати DataMatrix-
этикеток вместе с заданием выкачивается файл со всеми кодами, которые
будут напечатаны.
"""

from __future__ import annotations

from typing import Iterable, List


def build_codes_text(codes: Iterable[str]) -> str:
    """Собрать текст со всеми DataMatrix-кодами (один код на строку).

    Пустые коды (``None``/``''``) пропускаются. Возвращает строку с
    переводом строки в конце. Поднимает ``ValueError``, если кодов нет.
    """
    cleaned: List[str] = [str(c) for c in (codes or []) if c not in (None, '')]
    if not cleaned:
        raise ValueError('Нет кодов для формирования текстового файла')
    return '\n'.join(cleaned) + '\n'
