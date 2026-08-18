# helpers/printers.py

import asyncio
import socket
import time
from datetime import date
import logging
import re

from helper import CYRILLIC_CHARS

logger = logging.getLogger(__name__)

# Целевая длина УИП (DataMatrix): GTIN 14 + дата 6 + серийная часть 12 = 32 знака.
UIP_TARGET_LENGTH = 32


def process_uip_batch(batch: str, length: int = 12) -> str:
    """
    Подготовка партии для УИП (DataMatrix).

    Дополняет партию нулями с конца до заданной длины. По умолчанию 12 —
    максимальная длина серийного номера (внутреннего номера партии) в УИП
    по требованиям Честного Знака. Партия длиннее `length` обрезается.

    Пример: '1564' → '156400000000', 'A1/2026' → 'A1/2026000000'.

    Отдельный метод нужен, чтобы в будущем менять логику взаимодействия
    с партией (проверки, форматы, кодирование) в одном месте.
    """
    batch = (batch or '').strip()
    if not batch:
        return ''
    if len(batch) >= length:
        return batch[:length]
    return batch + '0' * (length - len(batch))


def _parse_zebra_hs(response: bytes) -> dict:
    """Парсинг ответа Zebra ~HS (2-3 строки в блоках STX..ETX).

    Используется и при опросе по отдельному подключению, и при опросе
    по уже открытому сокету во время печати.
    """
    if not response:
        return {'ok': False, 'error': 'Empty response'}

    # Декодируем и очищаем от управляющих символов
    raw = response.decode('ascii', errors='ignore')

    # Извлекаем блоки между \x02 и \x03
    blocks = re.findall(r'\x02(.*?)\x03', raw)

    if blocks:
        first_line = blocks[0]
        second_line = blocks[1] if len(blocks) > 1 else ''
    else:
        lines = [line.strip() for line in raw.split('\r\n') if line.strip()]
        if not lines:
            return {'ok': False, 'error': 'Cannot parse response', 'raw': raw}
        first_line = lines[0]
        second_line = lines[1] if len(lines) > 1 else ''

    p1 = first_line.split(',')
    p2 = second_line.split(',') if second_line else []

    # Строка 1: флаги по спецификации ~HS.
    paper_out = len(p1) > 1 and p1[1] == '1'
    paused = len(p1) > 2 and p1[2] == '1'
    formats_in_buffer = p1[4] if len(p1) > 4 else '0'
    buffer_full = len(p1) > 5 and p1[5] == '1'
    under_temp = len(p1) > 10 and p1[10] == '1'
    over_temp = len(p1) > 11 and p1[11] == '1'

    # Строка 2: head up (o) и ribbon out (p).
    head_up = len(p2) > 2 and p2[2] == '1'
    ribbon_out = len(p2) > 3 and p2[3] == '1'

    errors = []
    if paper_out:
        errors.append('нет бумаги')
    if ribbon_out:
        errors.append('нет ленты')
    if head_up:
        errors.append('открыта печатающая головка')
    if under_temp:
        errors.append('низкая температура головки')
    if over_temp:
        errors.append('высокая температура головки')
    if buffer_full:
        errors.append('буфер переполнен')

    return {
        'ok': True,
        'paused': paused,
        'error_flag': bool(errors),
        'errors': errors,
        'paper_out': paper_out,
        'ribbon_out': ribbon_out,
        'head_up': head_up,
        'buffer_full': buffer_full,
        'formats_in_buffer': formats_in_buffer,
        'message': 'Готов к печати' if not errors and not paused else (
            'Пауза' if paused and not errors else '; '.join(errors)
        ),
        'raw_first_line': first_line,
        'raw_full': raw[:200] + ('...' if len(raw) > 200 else ''),
    }


def check_printer_status(ip: str, port: int = 9100, timeout: float = 3.0) -> dict:
    """
    Получение статуса Zebra через команду ~HS.

    Формат ответа (ZPL II Programming Guide):
        \x02<line1>\x03\r\n\x02<line2>\x03\r\n...

    Строка 1: aaa,b,c,dddd,eee,f,g,h,iii,j,k,l
        aaa  = настройки интерфейса
        b    = paper out (1 = нет бумаги)
        c    = pause (1 = пауза)
        dddd = длина этикетки в точках
        eee  = количество форматов в буфере приёма
        f    = buffer full (1 = буфер переполнен)
        g    = диагностический режим
        h    = частичный формат
        j    = corrupt RAM
        k    = низкая температура
        l    = высокая температура

    Строка 2: mmm,n,o,p,q,r,s,t,uuuuuuuu,v,www
        mmm  = настройки функций
        o    = head up (1 = головка открыта)
        p    = ribbon out (1 = нет ленты)
        t    = label waiting
        uuuuuuuu = осталось этикеток в задании

    Пустой ответ (Empty response) — повторная попытка через 0.3с (принтер
    может быть временно занят обработкой ~JA или другой immediate-команды).
    """
    max_retries = 2
    for attempt in range(max_retries):
        try:
            with socket.create_connection((ip, port), timeout=timeout) as sock:
                # Небольшая пауза после подключения (Zebra требует)
                time.sleep(0.05)

                # Отправляем команду
                sock.sendall(b'~HS\r\n')

                # Читаем ответ с таймаутом (ждём минимум 2 строки из трёх)
                sock.settimeout(min(timeout, 2.0))
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

                if not response:
                    if attempt < max_retries - 1:
                        time.sleep(0.3)
                        continue
                    return {'ok': False, 'error': 'Empty response'}

                return _parse_zebra_hs(response)

        except ConnectionRefusedError:
            logger.error(f"Принтер {ip}:{port} отклоняет подключение")
            return {'ok': False, 'error': 'ConnectionRefused'}
        except socket.timeout:
            logger.warning(f"Таймаут при получении статуса от {ip}:{port}")
            return {'ok': False, 'error': 'Timeout'}
        except Exception as e:
            logger.exception(f"Ошибка при проверке статуса {ip}:{port}: {e}")
            return {'ok': False, 'error': str(e)}
    return {'ok': False, 'error': 'Empty response'}

def substitute_placeholders(
    zpl_code: str,
    *,
    batch_number: str,
    marking_date: date,
    expiration_date: date,
    current_box: int,
    gtin: str = '',
    gtin_unit: str = '',
    article: str = '',
    uip_include_batch: bool = True
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

    Плейсхолдеры УИП (DataMatrix, формат GS1):
        {uip_gtin}                — GTIN единицы продукции (14 цифр)
        {uip_marking_date}        — дата производства, ГГММДД
        {uip_article}             — артикул продукта
        {uip_batch}               — серийная часть УИП. Зависит от флага
                                    uip_include_batch:
                                      True  — партия (дополняется нулями);
                                      False — нули вместо партии.
                                    Серийная часть всегда 12 знаков
                                    (артикул + партия/нули), поэтому УИП
                                    всегда ровно 32 знака
                                    (GTIN + дата + артикул + серийная часть).
    """

    # Есть ли плейсхолдер артикула в шаблоне (проверяем до подстановки —
    # после замены плейсхолдер уже не найти).
    uip_article_in_template = '{uip_article}' in zpl_code

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

    # ── UIP (DataMatrix): GTIN единицы продукции ────────────────────────────────────────
    if gtin_unit and gtin_unit.strip():
        clean_gtin_unit = gtin_unit.strip()
        zpl_code = zpl_code.replace('{uip_gtin}', clean_gtin_unit)
    else:
        zpl_code = zpl_code.replace('{uip_gtin}', '')

    # ── UIP (DataMatrix): артикул продукта ─────────────────────────────────────────────
    if article and article.strip():
        zpl_code = zpl_code.replace('{uip_article}', article.strip())
    else:
        zpl_code = zpl_code.replace('{uip_article}', '')

    # ── GS1-128: даты ────────────────────────────────────────────────────────
    gs1_marking = marking_date.strftime('%y%m%d')
    gs1_expiration = expiration_date.strftime('%y%m%d')
    zpl_code = zpl_code.replace('{gs1_128_marking_date}', gs1_marking)
    zpl_code = zpl_code.replace('{gs1_128_expiry_date}', gs1_expiration) # основное
    zpl_code = zpl_code.replace('{gs1_128_expiration_date}', gs1_expiration) # alias

    # ── UIP (DataMatrix): дата производства (ГГММДД) ──────────────────────────
    zpl_code = zpl_code.replace('{uip_marking_date}', gs1_marking)

    # ── GS1-128: партия. Указывается дата производства.
    gs1_party = marking_date.strftime('%d%m%y')

    # Добавляем символ-разделитель.
    zpl_code = zpl_code.replace('{gs1_gs}', '')

    zpl_code = zpl_code.replace('{gs1_128_batch}', gs1_party) # основное
    zpl_code = zpl_code.replace('{gs1_128_batch_number}', gs1_party) # alias

    # ── UIP (DataMatrix): серийная часть (партия или нули) ────────────────────
    # Серийная часть УИП = 12 знаков (артикул + партия/нули), поэтому итоговый
    # УИП всегда ровно 32 знака: GTIN(14) + дата(6) + артикул + серийная часть.
    # Артикул учитывается только если его плейсхолдер реально есть в шаблоне.
    article_length = len((article or '').strip()) if uip_article_in_template else 0
    batch_slot = max(0, UIP_TARGET_LENGTH - 14 - 6 - article_length)

    if uip_include_batch:
        # С партией: партия, дополненная нулями до длины серийной части.
        zpl_code = zpl_code.replace(
            '{uip_batch}',
            process_uip_batch(batch_number, length=batch_slot),
        )
    else:
        # Без партии: вместо неё нули той же длины — длина УИП не меняется.
        zpl_code = zpl_code.replace('{uip_batch}', '0' * batch_slot)

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
    marking_batch_number = marking_date.strftime('%d%m%y')
    zpl_code = zpl_code.replace('{batch_number_str}', f'{batch_number}({marking_batch_number})')
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


# ---------------------------------------------------------------------------
# Управление принтерами (статус, очистка очереди, перезапуск)
# ---------------------------------------------------------------------------
# Zebra — ZPL:  ~HS (статус), ~JA (отмена всех заданий), ~JR (перезапуск)
# TSC   — TSPL: <ESC>!? / <ESC>!S (статус), CLS (очистка буфера), <ESC>!C (перезапуск)


def _parse_tsc_status(data: bytes) -> dict:
    """Парсинг расширенного статуса TSC <ESC>!S: <STX>[4 байта]<ETX><CR><LF>.

    Байт 1 — состояние: '@' (0x40) готов, 'P' (0x50) печать, 'W' (0x57)
    формирование изображения, '`' (0x60) пауза, 'E' (0x45) ошибка.
    Байт 2 — предупреждения: 'H' (0x48) = Receive buffer full.
    Байты 3-4 — ошибки ('A' перегрев, 'D' ошибка головки, 'H' застревание
    резака, 'P' нехватка памяти, '`' головка открыта и т.д.).
    """
    start = data.find(b'\x02')   # <STX>
    end = data.find(b'\x03')     # <ETX>
    if start == -1 or end == -1 or end - start < 5:
        return {'ok': False, 'error': 'Cannot parse <ESC>!S'}

    msg, warn, err1, err2 = data[start + 1:start + 5]
    errors = []
    if err1 == 0x41:
        errors.append('перегрев печатающей головки')
    if err1 == 0x42:
        errors.append('перегрев шагового двигателя')
    if err1 == 0x44:
        errors.append('ошибка печатающей головки')
    if err1 == 0x48:
        errors.append('застревание резака')
    if err1 == 0x50:
        errors.append('недостаточно памяти')
    if err2 == 0x41:
        errors.append('закончилась бумага')
    if err2 == 0x42:
        errors.append('замятие бумаги')
    if err2 == 0x44:
        errors.append('закончилась лента (риббон)')
    if err2 == 0x48:
        errors.append('застревание ленты')
    if err2 == 0x60:
        errors.append('открыта печатающая головка')

    paused = msg == 0x60     # '`'
    printing = msg in (0x50, 0x57)  # 'P' / 'W'
    buffer_full = warn == 0x48      # 'H'

    return {
        'ok': True,
        'paused': paused,
        'printing': printing,
        'error_flag': bool(errors),
        'errors': errors,
        'buffer_full': buffer_full,
        # Количество форматов TSC недоступно хосту (см. docstring).
        'formats_in_buffer': '?',
        'message': 'Готов к печати' if not errors and not paused else (
            'Идёт печать' if printing and not errors else '; '.join(errors) or 'Неизвестный статус'
        ),
        'raw': f"{chr(msg)}{chr(warn)}{chr(err1)}{chr(err2)}",
    }


def check_printer_status_on_socket(sock, printer_type: str = 'zebra',
                                   timeout: float = 1.0) -> dict:
    """Статус принтера по УЖЕ ОТКРЫТОМУ сокету (immediate-команды).

    Используется во время печати: некоторые TSC-принтеры (PEX) сбрасывают
    параллельные TCP-подключения, но отвечают на статус-команды в том же
    соединении, через которое идёт печать.

    Команды и формат ответа зависят от типа принтера — делегируется
    драйверу (helpers/printer_drivers.py).
    """
    from helpers.printer_drivers import get_driver_or_default
    return get_driver_or_default(printer_type).status_on_socket(sock, timeout)


def check_tsc_mileage_on_socket(sock, timeout: float = 1.5):
    """Пробег печати TSC (~!@): целая часть (обычно дюймы) + CR.

    Важно: запрос идёт по УЖЕ ОТКРЫТОМУ сокету. Во время печати по тому же
    сокету, что и этикетки, ~!@ встаёт за ними в потоке и не отвечает —
    поэтому при контроле потребления используем СВЕЖЕЕ подключение
    (check_tsc_mileage), когда принтер свободен (между пачками).
    Не отвечает — возвращаем None (не ошибку).
    """
    try:
        sock.settimeout(min(timeout, 2.0))
        sock.sendall(b'~!@\r\n')
        data = sock.recv(64)
        m = re.search(rb'(\d+)', data)
        if not m:
            return None
        return int(m.group(1))
    except (socket.timeout, ConnectionResetError, ConnectionError, OSError, ValueError):
        return None


def check_tsc_mileage(ip: str, port: int = 9100, timeout: float = 1.5):
    """Пробег TSC через отдельное (свежее) подключение.

    Используется между пачками, когда принтер свободен — в этом режиме
    запросы работают даже при заполненной очереди (проверено на PEX-2340).
    """
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            time.sleep(0.05)
            return check_tsc_mileage_on_socket(sock, timeout)
    except Exception:
        return None


def check_printer_status_tsc(ip: str, port: int = 9100, timeout: float = 3.0) -> dict:
    """Статус TSC-принтера.

    Основной запрос — <ESC>!S: принтер возвращает
    <STX>[4 байта]<ETX>, где:
      байт 1 — состояние: '`' (0x60) = пауза, 'P' (0x50) = печать,
                            'W' (0x57) = формирование изображения;
      байт 2 — предупреждения: 'H' (0x48) = Receive buffer full
                            (буфер приёма заполнен);
      байты 3-4 — ошибки ('A' перегрев, 'D' ошибка головки, 'H' застревание
                   резака, 'P' нехватка памяти, '`' головка открыта и т.д.).

    Количество этикеток в буфере TSC с хоста не запрашивается, свободная
    память (~!A) на PEX — константа (буфер приёма ~8 КБ), поэтому контроль
    буфера для TSC — темповая отправка + флаг переполнения (<ESC>!S).

    Если <ESC>!S не поддерживается (прошивка старше V6.29) — fallback на
    <ESC>!? (1 байт-маска) без контроля буфера.
    """
    # --- Основной запрос <ESC>!S ---
    detailed = None
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            time.sleep(0.05)
            sock.sendall(b'\x1b!S')
            sock.settimeout(min(timeout, 2.0))
            detailed = sock.recv(32)
    except ConnectionResetError as e:
        # Принтер занят и сбрасывает подключение (например, во время печати) —
        # повторный запрос fallback'ом бессмыслен, возвращаем ошибку сразу.
        return {'ok': False, 'error': f'ConnectionReset: {e}'}
    except Exception:
        # <ESC>!S может быть не поддержан прошивкой — пробуем fallback ниже.
        detailed = None

    if detailed:
        parsed = _parse_tsc_status(detailed)
        if parsed.get('ok'):
            return parsed
        # Ответ не распарсился — принтер, вероятно, не поддерживает <ESC>!S,
        # пробуем fallback ниже.

    # --- Fallback: <ESC>!? (1 байт-маска), если <ESC>!S не поддерживается ---
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            time.sleep(0.05)
            sock.sendall(b'\x1b!?')
            sock.settimeout(min(timeout, 2.0))
            data = sock.recv(16)

        if not data:
            return {'ok': False, 'error': 'Empty response'}

        status = data[0]
        errors = []
        if status & 0x01:
            errors.append('открыта печатающая головка')
        if status & 0x02:
            errors.append('замятие бумаги')
        if status & 0x04:
            errors.append('закончилась бумага')
        if status & 0x08:
            errors.append('закончилась лента (риббон)')
        if status & 0x80:
            errors.append('другая ошибка')

        paused = bool(status & 0x10)
        printing = bool(status & 0x20)

        # ok = True — принтер ответил (пауза/занятость/ошибки передаются
        # отдельными флагами, как в ~HS у Zebra). Иначе очередь печати
        # принимала бы паузу/печать за недоступность.
        return {
            'ok': True,
            'paused': paused,
            'printing': printing,
            'error_flag': bool(errors),
            'errors': errors,
            # <ESC>!? не даёт информации о буфере — контроль недоступен.
            'buffer_full': False,
            'formats_in_buffer': '?',
            'message': 'Готов к печати' if not errors and not paused else (
                'Идёт печать' if printing and not errors else '; '.join(errors) or 'Неизвестный статус'
            ),
            'raw': f'0x{status:02X}',
        }
    except ConnectionRefusedError:
        logger.error(f"Принтер TSC {ip}:{port} отклоняет подключение")
        return {'ok': False, 'error': 'ConnectionRefused'}
    except socket.timeout:
        logger.warning(f"Таймаут при получении статуса от TSC {ip}:{port}")
        return {'ok': False, 'error': 'Timeout'}
    except Exception as e:
        # Сетевой сбой (сброс соединения и т.п.) — обычная ситуация для
        # занятого принтера, логируем строкой без полного traceback.
        logger.warning(f"Ошибка при проверке статуса TSC {ip}:{port}: {e}")
        return {'ok': False, 'error': str(e)}


def check_printer_status_by_type(ip: str, port: int = 9100,
                                 printer_type: str = 'zebra',
                                 timeout: float = 3.0) -> dict:
    """Проверка статуса принтера по его типу.

    Запрос и формат ответа зависят от типа принтера (Zebra — ~HS,
    TSC — <ESC>!S/<ESC>!?): диспетчеризация выполняется через реестр
    драйверов (helpers/printer_drivers.py), что позволяет добавлять
    новые типы без правки этого модуля.
    """
    from helpers.printer_drivers import get_driver_or_default
    return get_driver_or_default(printer_type).status(ip, port, timeout)


def send_printer_command(ip: str, port: int, command: bytes,
                         timeout: float = 5.0) -> dict:
    """Отправка одиночной команды на принтер по TCP."""
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            sock.sendall(command)
        return {'success': True}
    except (socket.timeout, socket.error, OSError) as e:
        logger.error(f"Ошибка отправки команды на принтер {ip}:{port}: {e}")
        return {'success': False, 'error': str(e)}


def clear_printer_queue(ip: str, port: int = 9100, printer_type: str = 'zebra') -> dict:
    """Очистка очереди печати принтера.

    Команда зависит от типа принтера (Zebra — ~JA, TSC — <ESC>!.) и
    определяется драйвером (helpers/printer_drivers.py).
    """
    from helpers.printer_drivers import get_driver_or_default
    return get_driver_or_default(printer_type).clear_queue(ip, port)


def restart_printer(ip: str, port: int = 9100, printer_type: str = 'zebra') -> dict:
    """Перезапуск принтера (Zebra — ~JR, TSC — <ESC>!C)."""
    from helpers.printer_drivers import get_driver_or_default
    return get_driver_or_default(printer_type).restart(ip, port)


# ---------------------------------------------------------------------------
# Асинхронные обёртки
# ---------------------------------------------------------------------------
# Все сетевые функции выше — синхронные и блокирующие (socket.create_connection,
# recv, sendall с таймаутами). В async-контексте (воркеры очереди печати,
# веб-роутеры) их прямой вызов блокировал бы весь event loop, из-за чего
# «зависали» страницы при печати или недоступном принтере. Обёртки выполняют
# вызовы в отдельном потоке (asyncio.to_thread), не трогая event loop.

async def check_printer_status_async(ip: str, port: int = 9100,
                                     printer_type: str = 'zebra',
                                     timeout: float = 3.0) -> dict:
    """Проверка статуса принтера без блокировки event loop."""
    return await asyncio.to_thread(
        check_printer_status_by_type, ip, port, printer_type, timeout
    )


async def clear_printer_queue_async(ip: str, port: int = 9100,
                                    printer_type: str = 'zebra') -> dict:
    """Очистка очереди печати (Zebra ~JA / TSC CLS) без блокировки event loop."""
    return await asyncio.to_thread(
        clear_printer_queue, ip, port, printer_type
    )


async def restart_printer_async(ip: str, port: int = 9100,
                                printer_type: str = 'zebra') -> dict:
    """Перезапуск принтера (Zebra ~JR / TSC <ESC>!C) без блокировки event loop."""
    return await asyncio.to_thread(
        restart_printer, ip, port, printer_type
    )
