# test_codes_text.py
"""Тесты формирования текстового файла с DataMatrix-кодами (services/codes_text.py)."""

import pytest

from services.codes_text import build_codes_text

CODE_1 = '010460999000001121000001\x1d930001'
CODE_2 = '010460999000001121000002\x1d930002'


def test_build_text_one_code_per_line():
    text = build_codes_text([CODE_1, CODE_2])
    assert text == f'{CODE_1}\n{CODE_2}\n'


def test_build_text_has_trailing_newline():
    assert build_codes_text([CODE_1]).endswith('\n')


def test_single_code_roundtrip():
    assert build_codes_text([CODE_1]).rstrip('\n').split('\n') == [CODE_1]


def test_empty_codes_raise():
    with pytest.raises(ValueError):
        build_codes_text([])


def test_blank_codes_are_ignored():
    text = build_codes_text(['', CODE_1, None])
    assert text.rstrip('\n').split('\n') == [CODE_1]


def test_all_blank_codes_raise():
    with pytest.raises(ValueError):
        build_codes_text(['', None])


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
