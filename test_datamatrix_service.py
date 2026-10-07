# test_datamatrix_service.py
"""Тесты клиента внешнего сервиса кодов DataMatrix по UUID продукта.

Проверяем разбор успешного ответа, обработку ошибок сервиса, отсутствия
UUID и нулевого количества — без реальной сети (httpx.AsyncClient
подменяется фейком).
"""

import asyncio

import pytest

from services import datamatrix_service as svc
from services.datamatrix_service import (
    DatamatrixServiceError,
    fetch_datamatrix_codes_by_uuid,
)


class _FakeResponse:
    def __init__(self, payload=None, status_code=200, raise_exc=None):
        self._payload = payload
        self.status_code = status_code
        self._raise_exc = raise_exc

    def json(self):
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._payload


class _FakeClient:
    """Фейковый AsyncClient с записью последнего GET."""

    last_get = None
    last_timeout = None
    response = None

    def __init__(self, *args, **kwargs):
        _FakeClient.last_timeout = kwargs.get('timeout')

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, params=None, headers=None):
        _FakeClient.last_get = {'url': url, 'params': params, 'headers': headers}
        return _FakeClient.response


@pytest.fixture(autouse=True)
def _patch_client(monkeypatch):
    _FakeClient.last_get = None
    _FakeClient.last_timeout = None
    _FakeClient.response = None
    monkeypatch.setattr(svc.httpx, 'AsyncClient', _FakeClient)
    yield


def _run(coro):
    return asyncio.run(coro)


def test_fetch_returns_codes():
    _FakeClient.response = _FakeResponse(
        {'is_error': False, 'uuid_product': 'u-1', 'count': 2,
         'codes': ['c1', 'c2']},
    )
    codes = _run(fetch_datamatrix_codes_by_uuid(
        external_uuid='u-1', amount_codes=2,
    ))
    assert codes == ['c1', 'c2']
    assert _FakeClient.last_get['params'] == {
        'uuid_product': 'u-1', 'amount_codes': 2,
    }
    assert _FakeClient.last_get['url'].endswith(
        '/codes/api/get_codes_for_printer_by_product_uuid/'
    )


def test_fetch_issued_adds_flag():
    _FakeClient.response = _FakeResponse({'is_error': False, 'codes': []})
    _run(fetch_datamatrix_codes_by_uuid(
        external_uuid='u-1', amount_codes=1, issued=True,
    ))
    assert _FakeClient.last_get['params']['issued'] == '1'


def test_fetch_uses_default_timeout():
    _FakeClient.response = _FakeResponse({'is_error': False, 'codes': []})
    _run(fetch_datamatrix_codes_by_uuid(external_uuid='u-1', amount_codes=1))
    assert _FakeClient.last_timeout == svc.CODES_SERVICE_TIMEOUT


def test_fetch_passes_custom_timeout():
    _FakeClient.response = _FakeResponse({'is_error': False, 'codes': ['c1']})
    _run(fetch_datamatrix_codes_by_uuid(
        external_uuid='u-1', amount_codes=1, timeout=99.0,
    ))
    assert _FakeClient.last_timeout == 99.0


def test_fetch_empty_codes_is_ok():
    _FakeClient.response = _FakeResponse({'is_error': False, 'codes': []})
    assert _run(fetch_datamatrix_codes_by_uuid(
        external_uuid='u-1', amount_codes=5,
    )) == []


def test_fetch_service_error_raises():
    _FakeClient.response = _FakeResponse(
        {'is_error': True, 'message': 'Продукт не найден'},
    )
    with pytest.raises(DatamatrixServiceError, match='Продукт не найден'):
        _run(fetch_datamatrix_codes_by_uuid(
            external_uuid='u-1', amount_codes=1,
        ))


def test_fetch_http_error_uses_service_message():
    _FakeClient.response = _FakeResponse(
        {'is_error': True, 'message': 'Продукт с uuid=u-1 не найден.'},
        status_code=404,
    )
    with pytest.raises(DatamatrixServiceError, match='не найден'):
        _run(fetch_datamatrix_codes_by_uuid(
            external_uuid='u-1', amount_codes=1,
        ))


def test_fetch_http_error_without_message():
    _FakeClient.response = _FakeResponse(raise_exc=ValueError('not json'),
                                         status_code=500)
    with pytest.raises(DatamatrixServiceError, match='HTTP 500'):
        _run(fetch_datamatrix_codes_by_uuid(
            external_uuid='u-1', amount_codes=1,
        ))


def test_fetch_empty_uuid_raises_without_request():
    with pytest.raises(DatamatrixServiceError):
        _run(fetch_datamatrix_codes_by_uuid(
            external_uuid='   ', amount_codes=1,
        ))
    assert _FakeClient.last_get is None


def test_fetch_zero_amount_returns_empty_without_request():
    assert _run(fetch_datamatrix_codes_by_uuid(
        external_uuid='u-1', amount_codes=0,
    )) == []
    assert _FakeClient.last_get is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
