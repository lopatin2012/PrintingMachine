# helpers/printer_status.py

import socket
import time
from datetime import date
import logging
import re

from helper import CYRILLIC_CHARS

logger = logging.getLogger(__name__)


def check_printer_status(ip: str, port: int = 9100, timeout: float = 3.0) -> dict:
    """
    Получение статуса Zebra ZT610 через команду ~HS.

    Формат ответа:
        \x02<line1>\x03\r\n\x02<line2>\x03\r\n...

    Line 1 (основной статус):
        mode,paused,errors,head_heat,head_cold,paper_out,ribbon_out,label_taken,...
    """
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            # Небольшая пауза после подключения (Zebra требует)
            time.sleep(0.05)

            # Отправляем команду
            sock.sendall(b'~HS\r\n')

            # Читаем ответ с таймаутом
            sock.settimeout(2.0)
            response = b''

            while True:
                try:
                    chunk = sock.recv(512)
                    if not chunk:
                        break
                    response += chunk
                    # Если получили хотя бы один полный блок — достаточно для парсинга
                    if b'\x03\r\n' in response:
                        break
                except socket.timeout:
                    break

            if not response:
                return {'ok': False, 'error': 'Empty response'}

            # Декодируем и очищаем от управляющих символов
            raw = response.decode('ascii', errors='ignore')

            # Извлекаем все блоки между \x02 и \x03
            blocks = re.findall(r'\x02(.*?)\x03', raw)

            if not blocks:
                # Fallback: если нет маркеров, пробуем распарсить как есть
                lines = [line.strip() for line in raw.split('\r\n') if line.strip()]
                if lines:
                    first_line = lines[0]
                else:
                    return {'ok': False, 'error': 'Cannot parse response', 'raw': raw}
            else:
                first_line = blocks[0]  # Берём первый блок — основной статус

            # Парсим первую строку: mode,paused,errors,head_heat,...
            parts = first_line.split(',')

            if len(parts) >= 3:
                return {
                    'ok': True,
                    'paused': parts[2] == '1',  # 1 = принтер на паузе
                    'error_flag': parts[1] != '00000000',  # 00000000 = нет ошибок
                    'mode': parts[0] if len(parts) > 0 else 'unknown',
                    'head_heat': parts[3] if len(parts) > 3 else '0',
                    'paper_out': parts[5] == '1' if len(parts) > 5 else False,
                    'ribbon_out': parts[6] == '1' if len(parts) > 6 else False,
                    'raw_first_line': first_line,
                    'raw_full': raw[:200] + ('...' if len(raw) > 200 else ''),
                }

            return {'ok': True, 'paused': False, 'error_flag': False, 'raw': first_line}

    except ConnectionRefusedError:
        logger.error(f"Принтер {ip}:{port} отклоняет подключение")
        return {'ok': False, 'error': 'ConnectionRefused'}
    except socket.timeout:
        logger.warning(f"Таймаут при получении статуса от {ip}:{port}")
        return {'ok': False, 'error': 'Timeout'}
    except Exception as e:
        logger.exception(f"Ошибка при проверке статуса {ip}:{port}: {e}")
        return {'ok': False, 'error': str(e)}

def substitute_placeholders(
    zpl_code: str,
    *,
    batch_number: str,
    marking_date: date,
    expiration_date: date,
    current_box: int,
    gtin: str = ''
) -> str:
    """
    Единая функция подстановки плейсхолдеров — используется и при рендере
    предпросмотра (code_template.py), и при реальной печати (print_job.py).

    Плейсхолдеры в шаблоне:
        {gs1_128_marking_date}    — YYMMDD
        {gs1_128_expiry_date}     — YYMMDD  (alias: gs1_128_expiration_date)
        {gs1_128_batch}           — номер партии (alias: gs1_128_batch_number)
        {gs1_128_current_box}     — 5-значный номер коробки (alias: current_box)
        {marking_date_str}        — ДД.ММ.ГГ
        {expiration_date_str}     — ДД.ММ.ГГ
        {batch_number_str}        — партия(ДД.ММ.ГГ)
        {batch_number}            — номер партии как есть
    """

    # ── GS1-128: групповой GTIN ────────────────────────────────────────────────────────
    if gtin and gtin.strip():
        # Очищаем только от пробелов, остальное оставляем как есть
        clean_gtin = gtin.strip()
        zpl_code = zpl_code.replace('{gs1_gtin}', clean_gtin)
        zpl_code = zpl_code.replace('{gs1_gtin_short}', clean_gtin[1:])
    else:
        # Если GTIN пустой — просто удаляем плейсхолдер
        zpl_code = zpl_code.replace('{gs1_gtin}', '')
        zpl_code = zpl_code.replace('{gs1_gtin_short}', '')

    # ── GS1-128: даты ────────────────────────────────────────────────────────
    gs1_marking = marking_date.strftime('%y%m%d')
    gs1_expiration = expiration_date.strftime('%y%m%d')
    zpl_code = zpl_code.replace('{gs1_128_marking_date}', gs1_marking)
    zpl_code = zpl_code.replace('{gs1_128_expiry_date}', gs1_expiration) # основное
    zpl_code = zpl_code.replace('{gs1_128_expiration_date}', gs1_expiration) # alias

    # ── GS1-128: партия. Указывается дата производства.
    gs1_party = marking_date.strftime('%d%m%y')
    # Добавляем символ-разделитель как в 1С.
    gs1_party += ""

    zpl_code = zpl_code.replace('{gs1_128_batch}', gs1_party) # основное
    zpl_code = zpl_code.replace('{gs1_128_batch_number}', gs1_party) # alias

    # ── GS1-128: номер коробки ───────────────────────────────────────────────
    box_str = f"{current_box:05d}"
    zpl_code = zpl_code.replace('{gs1_128_current_box}', box_str) # основное
    zpl_code = zpl_code.replace('{current_box}', box_str) # alias

    # ── Человекочитаемые даты ДД.ММ.ГГ ──────────────────────────────────────
    marking_fmt = marking_date.strftime('%d.%m.%y')
    expiration_fmt = expiration_date.strftime('%d.%m.%y')
    zpl_code = zpl_code.replace('{marking_date_str}', marking_fmt)
    zpl_code = zpl_code.replace('{expiration_date_str}', expiration_fmt)

    # ── Партия (человекочитаемая) ────────────────────────────────────────────
    zpl_code = zpl_code.replace('{batch_number_str}', f'{batch_number}({marking_fmt})')
    zpl_code = zpl_code.replace('{batch_number}', batch_number)

    # ── Гарантируем закрытие этикетки ────────────────────────────────────────
    if not zpl_code.strip().endswith('^XZ'):
        zpl_code = zpl_code.strip() + '\n^XZ'

    return zpl_code

def str_to_zpl_hex(text: str, encoding: str = 'UTF-8') -> str:
    """Преобразование строки в побайтовую HEX-строку для ZPL."""
    try:
        encoded = text.encode(encoding)
    except UnicodeEncodeError:
        encoded = text.encode(encoding, errors='replace')
    return ''.join(f'_{b:02X}' for b in encoded)

def replace_cyrillic_in_zpl(zpl_code: str) -> str:
    """Замена всех кириллических символов в ZPL-коде на HEX-представление."""
    result = []
    for char in zpl_code:
        if char in CYRILLIC_CHARS:
            result.append(str_to_zpl_hex(char))
        else:
            result.append(char)
    return ''.join(result)

def send_zpl_safely(sock: socket.socket, data: bytes, chunk_size: int = 4096) -> None:
    """
    Отправка ZPL-данных на принтер по частям с подтверждением записи.
    """
    # Включаем TCP_NODELAY, чтобы каждый chunk уходил сразу, а не буферизовался
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    offset = 0
    total = len(data)
    while offset < total:
        end = min(offset + chunk_size, total)
        sent = sock.send(data[offset:end])
        if sent == 0:
            raise OSError("Соединение с принтером разорвано в процессе отправки")
        offset += sent
