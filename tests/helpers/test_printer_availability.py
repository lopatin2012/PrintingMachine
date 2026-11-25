"""Проверка сообщений о недоступности принтера.

При недоступном принтере задание не создаётся и коды DataMatrix не
запрашиваются — пользователь должен увидеть понятную причину.
"""
from helpers.printers import (
    describe_printer_unavailable,
    printer_unavailable_message,
)


def test_timeout_reason():
    assert describe_printer_unavailable(
        {'ok': False, 'error': 'Timeout'}
    ) == 'нет ответа (таймаут)'


def test_connection_refused_reason():
    for error in ('ConnectionRefused', 'connection refused',
                  '[WinError 10061] No connection could be made'):
        reason = describe_printer_unavailable({'ok': False, 'error': error})
        if 'WinError' in error:
            # Системный текст не распознан — возвращается как есть.
            assert reason == error
        else:
            assert reason == 'отказ в подключении'


def test_empty_response_reason():
    assert describe_printer_unavailable(
        {'ok': False, 'error': 'Empty response'}
    ) == 'принтер не ответил'


def test_unknown_error_is_passed_through():
    assert describe_printer_unavailable(
        {'ok': False, 'error': 'No route to host'}
    ) == 'No route to host'


def test_missing_error_means_no_link():
    assert describe_printer_unavailable({'ok': False}) == 'нет связи'
    assert describe_printer_unavailable(None) == 'нет связи'


def test_message_mentions_printer_and_no_codes():
    message = printer_unavailable_message(
        'Zebra цех 1', {'ok': False, 'error': 'Timeout'}
    )
    assert 'Zebra цех 1' in message
    assert 'недоступен' in message
    assert 'нет ответа (таймаут)' in message
    assert 'коды DataMatrix не запрашивались' in message
    assert 'Задание не создано' in message
