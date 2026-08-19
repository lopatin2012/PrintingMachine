# helpers/printer_drivers.py
"""Драйверы принтеров — единая точка расширения типов принтеров.

Каждый тип принтера описывается классом-драйвером, который инкапсулирует
всё поведение, специфичное для этого типа:

  * запрос статуса (status / status_on_socket);
  * очистка очереди (clear_queue) и перезапуск (restart);
  * особенности отправки этикеток (пачками с отдельным подключением или
    непрерывно по постоянному соединению) и контроль буфера принтера;
  * контроль очереди по пробегу (актуально для аппликаторов TSC).

Чтобы добавить новый тип принтера, достаточно реализовать подкласс
PrinterDriver и зарегистрировать его через @register_driver — валидация
типов, списки в интерфейсе, статусы и логика очереди печати подхватят
его автоматически (см. README, раздел «Типы принтеров»).
"""
import logging
import os
import re
import socket
import time
from abc import ABC

from helpers.printers import (
    _parse_tsc_status,
    _parse_zebra_hs,
    check_printer_status,      # Zebra ~HS
    check_printer_status_tsc,  # TSC <ESC>!S / <ESC>!?
    check_tsc_mileage,
    send_printer_command,
)

logger = logging.getLogger(__name__)


class PrinterDriver(ABC):
    """Базовый класс драйвера принтера.

    Атрибуты-флаги определяют поведение очереди печати:
      * batch_send     — отправка этикеток пачками: каждая пачка своим
                         TCP-подключением. Для TSC/PEX это требование
                         (принтер принимает одно соединение одновременно),
                         для ZPL — ограничение очереди (не «заливать»
                         медленный принтер больше, чем на buffer_limit
                         этикеток «впереди» реальной печати);
      * mileage_gate   — перед пачкой ждать, пока принтер напечатает часть
                         ранее отправленных этикеток (контроль по пробегу);
      * buffer_control — контроль очереди принтера: 'formats' — по числу
                         форматов в буфере (~HS), 'full_flag' — только по
                         флагу переполнения, None — без контроля.
    """

    # Уникальный ключ типа (значение printer_type в БД).
    key: str = ''
    # Человекочитаемое название для интерфейса.
    label: str = ''
    # Краткое описание (подсказка в форме добавления принтера).
    description: str = ''

    # Поведение очереди печати.
    batch_send: bool = False
    mileage_gate: bool = False
    buffer_control: str = 'formats'

    # Команды протокола (байты).
    status_cmd: bytes = b'~HS\r\n'
    clear_cmd: bytes = b'~JA'
    restart_cmd: bytes = b'~JR'

    # ── Статус ──────────────────────────────────────────────────────────

    def status(self, ip: str, port: int = 9100, timeout: float = 3.0) -> dict:
        """Статус принтера (отдельное подключение)."""
        return check_printer_status(ip, port, timeout)

    def status_on_socket(self, sock, timeout: float = 1.0) -> dict:
        """Статус по уже открытому сокету (во время печати)."""
        try:
            sock.settimeout(min(timeout, 2.0))
            sock.sendall(self.status_cmd)
            response = b''
            while True:
                try:
                    chunk = sock.recv(512)
                    if not chunk:
                        break
                    response += chunk
                    if response.count(b'\x03\r\n') >= 2:
                        break
                except socket.timeout:
                    break
            return _parse_zebra_hs(response)
        except (socket.timeout, ConnectionResetError, ConnectionError, OSError) as e:
            return {'ok': False, 'error': str(e)}

    # ── Управление ─────────────────────────────────────────────────────

    def clear_queue(self, ip: str, port: int = 9100) -> dict:
        """Очистить очередь печати принтера.

        После команды очистки принтеру нужно время на обработку — пауза
        0.5с перед возвратом гарантирует, что следующий запрос статуса
        не получит пустой ответ.
        """
        result = send_printer_command(ip, port, self.clear_cmd)
        if result.get('success'):
            time.sleep(0.5)
        return result

    def restart(self, ip: str, port: int = 9100) -> dict:
        """Перезапустить принтер."""
        return send_printer_command(ip, port, self.restart_cmd)

    # ── Параметры печати и пауза (страница «Контроль принтеров») ────────
    # Диапазоны значений для формы управления (валидируются драйвером).
    contrast_min: int = 0
    contrast_max: int = 30
    speed_min: int = 1
    speed_max: int = 14

    def set_contrast(self, ip: str, port: int = 9100, value: int = None) -> dict:
        """Установить контраст (плотность) печати."""
        return {
            'success': False,
            'error': 'Установка контраста не поддерживается для этого типа принтера',
        }

    def set_speed(self, ip: str, port: int = 9100, value: int = None) -> dict:
        """Установить скорость печати (дюймов в секунду)."""
        return {
            'success': False,
            'error': 'Установка скорости не поддерживается для этого типа принтера',
        }

    def pause(self, ip: str, port: int = 9100) -> dict:
        """Поставить принтер на паузу."""
        return {
            'success': False,
            'error': 'Пауза не поддерживается для этого типа принтера',
        }

    def resume(self, ip: str, port: int = 9100) -> dict:
        """Снять принтер с паузы."""
        return {
            'success': False,
            'error': 'Возобновление не поддерживается для этого типа принтера',
        }

    # ── Контроль очереди (аппликаторы) ─────────────────────────────────

    def mileage(self, ip: str, port: int = 9100, timeout: float = 1.5):
        """Пробег печати для контроля очереди; None — не поддерживается."""
        return None

    def label_length_inches(self, code: str):
        """Длина этикетки в дюймах из шаблона; None — вычислить нельзя."""
        return None


class ZebraDriver(PrinterDriver):
    """Принтеры Zebra (ZPL) с пачечной отправкой и контролем буфера по ~HS.

    Пачечная отправка (как у TSC): этикетки уходят пачками по batch_size,
    между пачками принтер свободен и отвечает на статус, а гейт по числу
    форматов в буфере (~HS eee) не позволяет «заливать» очередь медленного
    принтера больше, чем на buffer_limit этикеток «впереди» печати.
    """

    key = 'zebra'
    label = 'Zebra'
    description = 'ZPL-принтеры Zebra (ZT/ZX и др.) — пачечная отправка, контроль буфера по ~HS'

    batch_send = True

    # ── Параметры печати и пауза (команды SGD, работают по TCP 9100) ─────

    def set_contrast(self, ip: str, port: int = 9100, value: int = None) -> dict:
        value = int(value)
        if not (self.contrast_min <= value <= self.contrast_max):
            return {
                'success': False,
                'error': f'Контраст должен быть от {self.contrast_min} до {self.contrast_max}',
            }
        return send_printer_command(
            ip, port, f'~SD{value}"\r\n'.encode())

    def set_speed(self, ip: str, port: int = 9100, value: int = None) -> dict:
        value = int(value)
        if not (self.speed_min <= value <= self.speed_max):
            return {
                'success': False,
                'error': f'Скорость должна быть от {self.speed_min} до {self.speed_max} дюймов/с',
            }
        return send_printer_command(
            ip, port, f'^PR{value},{value}"\r\n'.encode())

    def pause(self, ip: str, port: int = 9100) -> dict:
        return send_printer_command(ip, port, b'~JP\r\n')

    def resume(self, ip: str, port: int = 9100) -> dict:
        return send_printer_command(ip, port, b'~PS\r\n')


class TscDriver(PrinterDriver):
    """Аппликаторы TSC (PEX-2340 и др.).

    Принимают только одно TCP-подключение одновременно, поэтому этикетки
    отправляются пачками (каждая пачка — своё подключение), а очередь
    контролируется по пробегу печати.
    """

    key = 'tsc'
    label = 'TSC'
    description = 'Аппликаторы TSC (PEX и др.) — пачечная отправка, контроль по пробегу'

    batch_send = True
    mileage_gate = True
    buffer_control = 'full_flag'

    status_cmd = b'\x1b!S'
    clear_cmd = b'\x1b!.'
    restart_cmd = b'\x1b!C'

    # Диапазоны параметров печати TSPL2 (DENSITY 0-15, SPEED 1-6).
    contrast_min: int = 0
    contrast_max: int = 15
    speed_min: int = 1
    speed_max: int = 6

    def set_contrast(self, ip: str, port: int = 9100, value: int = None) -> dict:
        value = int(value)
        if not (self.contrast_min <= value <= self.contrast_max):
            return {
                'success': False,
                'error': f'Контраст должен быть от {self.contrast_min} до {self.contrast_max}',
            }
        # Команда TSPL2 DENSITY; для конкретной модели может потребоваться
        # уточнение (например, через панель принтера).
        return send_printer_command(ip, port, f'DENSITY {value}\r\n'.encode())

    def set_speed(self, ip: str, port: int = 9100, value: int = None) -> dict:
        value = int(value)
        if not (self.speed_min <= value <= self.speed_max):
            return {
                'success': False,
                'error': f'Скорость должна быть от {self.speed_min} до {self.speed_max} дюймов/с',
            }
        return send_printer_command(ip, port, f'SPEED {value}\r\n'.encode())

    def pause(self, ip: str, port: int = 9100) -> dict:
        return send_printer_command(ip, port, b'PAUSE\r\n')

    def resume(self, ip: str, port: int = 9100) -> dict:
        return send_printer_command(ip, port, b'RESUME\r\n')

    def status(self, ip: str, port: int = 9100, timeout: float = 3.0) -> dict:
        return check_printer_status_tsc(ip, port, timeout)

    def status_on_socket(self, sock, timeout: float = 1.0) -> dict:
        try:
            sock.settimeout(min(timeout, 2.0))
            sock.sendall(b'\x1b!S')
            data = sock.recv(32)
            return _parse_tsc_status(data)
        except (socket.timeout, ConnectionResetError, ConnectionError, OSError) as e:
            return {'ok': False, 'error': str(e)}

    def mileage(self, ip: str, port: int = 9100, timeout: float = 1.5):
        return check_tsc_mileage(ip, port, timeout)

    def label_length_inches(self, code: str):
        """Длина этикетки в дюймах: из ^LL (точек) и плотности TSC_DPI.

        Приоритет: TSC_MILEAGE_PER_LABEL (дюймы на этикетку), затем расчёт
        из шаблона. Вернёт None, если вычислить нельзя (гейт отключится).
        """
        override = os.getenv('TSC_MILEAGE_PER_LABEL')
        if override:
            try:
                return float(override)
            except ValueError:
                logger.warning('TSC_MILEAGE_PER_LABEL=%r — не число, игнорирую', override)
        m = re.search(r'\^LL(\d+)', code or '')
        if not m:
            return None
        dpi = int(os.getenv('TSC_DPI', '203'))
        return int(m.group(1)) / dpi


class GenericZplDriver(ZebraDriver):
    """ZPL-совместимые принтеры других производителей.

    Пример третьего типа: поведение как у Zebra (непрерывная отправка,
    контроль буфера по ~HS), но собственный ключ в реестре — подходит для
    Honeywell, Datamax, Argox и т.п., работающих на языке ZPL.
    """

    key = 'zpl'
    label = 'ZPL-совместимый'
    description = 'ZPL-принтеры Honeywell, Datamax, Argox и др.'


# ── Реестр драйверов ────────────────────────────────────────────────────────

_DRIVERS: dict[str, PrinterDriver] = {}
_ORDER: list[str] = []


def register_driver(driver: PrinterDriver) -> PrinterDriver:
    """Зарегистрировать драйвер в реестре (ключ приводится к нижнему регистру)."""
    key = (driver.key or '').strip().lower()
    if not key:
        raise ValueError('Ключ драйвера не может быть пустым')
    _DRIVERS[key] = driver
    if key not in _ORDER:
        _ORDER.append(key)
    return driver


def get_printer_driver(printer_type) -> PrinterDriver | None:
    """Драйвер по типу принтера; None для неизвестного типа."""
    return _DRIVERS.get((printer_type or '').strip().lower())


def get_driver_or_default(printer_type) -> PrinterDriver:
    """Драйвер по типу; для неизвестного типа — Zebra (поведение по умолчанию)."""
    return get_printer_driver(printer_type) or _DRIVERS['zebra']


def printer_types() -> list[dict]:
    """Список поддерживаемых типов для валидации и интерфейса."""
    return [
        {
            'key': _DRIVERS[k].key,
            'label': _DRIVERS[k].label,
            'description': _DRIVERS[k].description,
        }
        for k in _ORDER
    ]


def printer_type_label(printer_type) -> str:
    """Человекочитаемое название типа для отображения."""
    driver = get_printer_driver(printer_type)
    return driver.label if driver else (printer_type or '—')


# Регистрация встроенных драйверов. Новый тип = новый подкласс + register_driver().
register_driver(ZebraDriver())
register_driver(TscDriver())
register_driver(GenericZplDriver())
