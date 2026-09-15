# test_datamatrix_service.py
"""Тесты интеграции с внешним сервисом кодов (services/datamatrix_service.py)
и подстановки DataMatrix-кодов в ZPL (по одному коду на этикетку).

Внешний HTTP не выполняется: httpx.AsyncClient подменяется фейком.
Тесты чистые — не нужны БД, .env или принтер.
"""

import asyncio
from datetime import date

import httpx
import pytest

import services.datamatrix_service as dm
from helpers.printers import substitute_placeholders


# ---------------------------------------------------------------------------
# Фейковый httpx.AsyncClient
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, json_data=None, status_code=200, json_error=None):
        self._json_data = json_data
        self._json_error = json_error
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f'HTTP {self.status_code}',
                request=httpx.Request('GET', 'http://test/codes'),
                response=self,
            )

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._json_data


class _FakeClient:
    def __init__(self, response=None, error=None, captured=None):
        self._response = response
        self._error = error
        self._captured = captured if captured is not None else {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None):
        self._captured['url'] = url
        self._captured['params'] = params
        self._captured['headers'] = headers
        if self._error is not None:
            raise self._error
        return self._response


def _patch_client(monkeypatch, response=None, error=None):
    """Подменить httpx.AsyncClient фейком, вернуть словарь с захваченными данными."""
    captured = {}

    def factory(*args, **kwargs):
        return _FakeClient(response=response, error=error, captured=captured)

    monkeypatch.setattr(dm.httpx, 'AsyncClient', factory)
    return captured


# ---------------------------------------------------------------------------
# Разбор ответа сервиса
# ---------------------------------------------------------------------------

def test_extract_codes_variants():
    assert dm._extract_codes(['a', 'b']) == ['a', 'b']
    assert dm._extract_codes([{'code': 'a'}, {'datamatrix': 'b'}]) == ['a', 'b']
    assert dm._extract_codes([{'value': 'a'}, None, '']) == ['a']
    assert dm._extract_codes({'codes': ['a']}) == ['a']
    assert dm._extract_codes({'datamatrix': ['a', 'b']}) == ['a', 'b']
    assert dm._extract_codes({'data': {'codes': ['x', 'y']}}) == ['x', 'y']
    assert dm._extract_codes({'result': [{'value': 'z'}]}) == ['z']
    assert dm._extract_codes({}) == []
    assert dm._extract_codes(None) == []


# ---------------------------------------------------------------------------
# GET /codes/api/get_codes_by_product/
# ---------------------------------------------------------------------------

def test_fetch_codes_by_product_uuid_builds_get_request(monkeypatch):
    monkeypatch.setattr(dm, 'CODES_SERVICE_URL', 'http://127.0.0.1:8000')
    captured = _patch_client(
        monkeypatch, response=_FakeResponse({'codes': ['CODE-A', 'CODE-B']})
    )

    codes = asyncio.run(dm.fetch_codes_by_product_uuid(
        external_uuid='11111111-2222-3333-4444-555555555555', count=2,
    ))

    assert codes == ['CODE-A', 'CODE-B']
    assert captured['url'] == 'http://127.0.0.1:8000/codes/api/get_codes_by_product/'
    assert captured['params'] == {
        'uuid_product': '11111111-2222-3333-4444-555555555555',
        'count': 2,
    }


def test_fetch_codes_by_product_uuid_accepts_plain_list(monkeypatch):
    _patch_client(monkeypatch, response=_FakeResponse(['A', 'B', 'C']))

    codes = asyncio.run(dm.fetch_codes_by_product_uuid(
        external_uuid='u', count=3,
    ))

    assert codes == ['A', 'B', 'C']


def test_fetch_codes_by_product_uuid_empty_response(monkeypatch):
    _patch_client(monkeypatch, response=_FakeResponse({'codes': []}))

    codes = asyncio.run(dm.fetch_codes_by_product_uuid(
        external_uuid='u', count=5,
    ))

    assert codes == []


def test_fetch_codes_by_product_uuid_requires_uuid():
    with pytest.raises(dm.DatamatrixServiceError):
        asyncio.run(dm.fetch_codes_by_product_uuid(external_uuid='   ', count=1))


def test_fetch_codes_by_product_uuid_network_error(monkeypatch):
    _patch_client(monkeypatch, error=httpx.ConnectError('boom'))

    with pytest.raises(dm.DatamatrixServiceError):
        asyncio.run(dm.fetch_codes_by_product_uuid(external_uuid='u', count=1))


def test_fetch_codes_by_product_uuid_http_error(monkeypatch):
    _patch_client(monkeypatch, response=_FakeResponse(status_code=500))

    with pytest.raises(dm.DatamatrixServiceError):
        asyncio.run(dm.fetch_codes_by_product_uuid(external_uuid='u', count=1))


# ---------------------------------------------------------------------------
# Подстановка кода в ZPL: новый код на каждую этикетку
# ---------------------------------------------------------------------------

_DM_ZPL = '^XA^PW400^LL200^FO10,10^BXN,2,150^FD{datamatrix}^FS^XZ'


def test_substitute_datamatrix_placeholder():
    out = substitute_placeholders(
        _DM_ZPL,
        batch_number='01',
        marking_date=date(2026, 3, 5),
        expiration_date=date(2026, 3, 31),
        current_box=1,
        datamatrix='010460123456789021ABC123',
    )
    assert '010460123456789021ABC123' in out
    assert '{datamatrix}' not in out


def test_substitute_datamatrix_missing_removes_placeholder():
    out = substitute_placeholders(
        _DM_ZPL,
        batch_number='01',
        marking_date=date(2026, 3, 5),
        expiration_date=date(2026, 3, 31),
        current_box=1,
    )
    assert '{datamatrix}' not in out


def test_datamatrix_new_code_per_label():
    """На каждую коробку подставляется свой код из списка."""
    codes = ['CODE-1', 'CODE-2', 'CODE-3']
    labels = [
        substitute_placeholders(
            _DM_ZPL,
            batch_number='01',
            marking_date=date(2026, 3, 5),
            expiration_date=date(2026, 3, 31),
            current_box=i + 1,
            datamatrix=codes[i],
        )
        for i in range(len(codes))
    ]

    assert all(codes[i] in labels[i] for i in range(len(codes)))
    assert len(set(labels)) == len(codes)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
