# test_auth_token_expiry.py
"""Сессии по умолчанию бессрочные (токен без claim'а ``exp``).

Срок можно задать через env ``ACCESS_TOKEN_EXPIRE_MINUTES`` (> 0) — тогда
добавляется ``exp``. Тесты подменяют константу модуля, чтобы не зависеть от env.
"""

from datetime import timedelta

from jose import jwt

from security import ALGORITHM, SECRET_KEY, create_access_token
import security


def _payload(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def test_infinite_token_when_minutes_zero(monkeypatch):
    monkeypatch.setattr(security, 'ACCESS_TOKEN_EXPIRE_MINUTES', 0)
    token = create_access_token({'sub': 'user-1'})
    payload = _payload(token)
    assert 'exp' not in payload, 'у бессрочного токена не должно быть exp'
    assert payload['sub'] == 'user-1'


def test_token_gets_exp_when_minutes_configured(monkeypatch):
    monkeypatch.setattr(security, 'ACCESS_TOKEN_EXPIRE_MINUTES', 60)
    token = create_access_token({'sub': 'user-1'})
    assert 'exp' in _payload(token)


def test_explicit_expires_delta_is_respected(monkeypatch):
    monkeypatch.setattr(security, 'ACCESS_TOKEN_EXPIRE_MINUTES', 0)
    token = create_access_token({'sub': 'user-1'}, expires_delta=timedelta(minutes=5))
    assert 'exp' in _payload(token)


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
