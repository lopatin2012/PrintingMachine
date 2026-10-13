# test_auth_required.py
"""Защищённые страницы при отсутствии сессии должны редиректить на вход.

Раньше ``get_current_user`` возвращал None, а обработчики (например,
``/printing``) сразу обращались к ``current_user.id`` — страница падала с 500
при отсутствии/просрочке токена. Теперь ``get_current_user`` отправляет гостя
на ``user_login``; гостевыми остаются главная и polling-эндпоинты.
"""

from starlette.testclient import TestClient

from main import app


def test_printing_redirects_to_login_when_anonymous():
    client = TestClient(app, follow_redirects=False)
    r = client.get('/printing')
    assert r.status_code == 302, r.status_code
    assert r.headers.get('location') == 'user_login'


def test_printing_history_redirects_to_login_when_anonymous():
    client = TestClient(app, follow_redirects=False)
    r = client.get('/printing/history')
    assert r.status_code == 302, r.status_code
    assert r.headers.get('location') == 'user_login'


def test_home_available_for_anonymous():
    """Главная доступна гостю (там current_user может быть None)."""
    client = TestClient(app)
    r = client.get('/')
    assert r.status_code == 200, r.status_code


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
