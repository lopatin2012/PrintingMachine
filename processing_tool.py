import re
import logging
from ipaddress import ip_address

import shutil

# Логирование.
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

cyrillic = list('АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя')

def validate_ip(ip: str) -> bool:
    try:
        ip_address(ip)
        return True
    except ValueError:
        return False

class ProcessingToolZPL:
    """
    Инструмент для взаимодействия с ZPL кодом.
    """

    # Команды принтера Zebra.
    # ^XA - Начало команды.
    # ^XZ - Конец команды.
    # ~JR - Перезагрузка.
    # ~JS - Очистить очередь печать на принтере. Не всегда всё чистит.
    # ^PW - Размер этикетки. Ширина.
    # ^LL - Размер этикетки. Высота.
    # ~SD - Плотность. До 30.
    # ~PR - Скорость. До 10.
    # ^CI28 - Включение кириллицы.
    # ^FO30,150 ^BXN,4,200,,,,\,1 ^FD\10104601751028976215zkWE1\193Rhoi^FS - DataMatrix.

    def __init__(self):
        self.rotation_map = {'N': 0, 'R': 90, 'B': 180, 'I': 270}
        self.fonts = {
            '0': 'Стандартный. Поддерживает кириллицу',
            '@': 'Цифровой. Не поддерживает кириллицу'
        }

    def get_info_font_hint(self):
        return [
            print(f'Номер шрифта: {k}. Особенности: {v}')
            for k, v in self.fonts.items()
        ]

    def str_to_zpl_hex(
            self,
            text: str,
            encoding: str = 'UTF-8'
    ) -> str:
        """
        Преобразование текстовой строки в побайтовую строку для печати на принтере.
        :param text:
        :param encoding:
        :return:
        """

        try:
            encoded = text.encode(encoding)
        except UnicodeEncodeError as e:
            encoded = text.encode(encoding, errors='replace')
        return ''.join(f'_{b:02X}' for b in encoded)

    @staticmethod
    def is_cyrillic(
            symbol
    ):

        return True if symbol in cyrillic else False

    def replace_symbol_cyrillic(
            self,
            string_line
    ):
        new_string_line = ""
        for symbol in string_line:
            new_string_line += self.str_to_zpl_hex(symbol) if self.is_cyrillic(symbol) else symbol

        return new_string_line

    def command_clear(
            self,
            encoding: str = 'cp1251'
    ) -> bytes:
        """
        Команда очистки очереди печати.
        :return:
        """
        return "~JA".encode(encoding)

    def command_reset(self, encoding: str = 'cp1251') -> bytes:
        """
        Команда перезагрузки.
        :return:
        """
        return "~JR".encode(encoding)

    def command_graphing_sensor_calibration(self, encoding: str = 'cp1251') -> bytes:
        """
        Команда печати графика состояния печатающей головки.
        :return:
        """
        return "~JG".encode(encoding)

    def command_set_darkness_of_printing(
            self,
            value: int = 17,
            encoding: str = 'cp1251'
    ) -> bytes:
        """
        Команда установки плотности печати.
        :return:
        """
        return fr"~SD{value}".encode(encoding)

    def command_set_size_label(
            self,
            width: int = 800,
            length: int = 700,
            encoding: str = 'cp1251'
    ) -> bytes:
        """
        Команда размеров этикетки.
        :return:
        """
        return fr"^XA^PW{width}^LL{length}^XZ".encode(encoding)

    def add_text_to_command(
            self,
            indent_x: int,
            indent_y: int,
            value: str,
            height_font: int,
            width_font: int,
            rotation: str = "N",
            font: str = "0",
    ):
        """
        Добавить текст в команду.
        :return:
        """
        return fr"""
        ^FO{indent_x},{indent_y}
        ^A{font}{rotation},{height_font},{width_font}
        ^FH^FD{self.str_to_zpl_hex(value)}^FS
        """

    def add_image_to_command(
            self,
            indent_x: int,
            indent_y: int,
            compression_type: str,
            binary_byte_count: int,
            graphic_field_count: int,
            bytes_per_row: int,
            data: str
    ):
        """
        Добавить изображение в команду.
        :return:
        """
        return fr"""
        ^FO{indent_x},{indent_y}
        ^GF{compression_type},
        {binary_byte_count},{graphic_field_count},
        {bytes_per_row},{data}^FS
        """

    def generate_zpl_from_template(
            self,
            template: str,
            batch: str,
            marking_date: str,
            expiration_date: str,
            box_number: int
    ) -> str:
        """
        Подставляем значения в шаблоне.
        :param template:
        :param batch:
        :param marking_date:
        :param expiration_date:
        :param box_number:
        :return:
        """
        return template.format(
            batch=batch,
            marking_date=marking_date,
            expiration_date=expiration_date,
            box_number=box_number
        )

    def send_to_printer(
            self,
            zpl_commands: list[str], ip: str, port: int = 9100
    ) -> bool:
        """
        Отправка данных для печати на принтер.
        :return:
        """
        import socket

        # Проверка корректности ip адреса.
        is_valid_ip = validate_ip(ip)
        if not is_valid_ip:
            logger.error(f"Некорректный IP-адрес")
            return False

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5)
                sock.connect((ip, port))

                for cmd in zpl_commands:
                    correct_string_line = self.replace_symbol_cyrillic(cmd)
                    sock.sendall(correct_string_line.encode('cp1251'))

            return True
        except Exception as e:
            logger.error(f"Ошибка отправки данных для печати на принтер: {ip}: {port} - {e}")
            return False

    def parse_zpl(
            self,
            zpl: str,
    ):
        """
        Парсим zpl код для отрисовки.
        :param zpl:
        :return:
        """

        # Удаления начала и конца строки.
        zpl = zpl.replace('^XA', '').replace('^XZ', '')

        # Разделение по командам ^FS
        raw_commands = [cmd.strip() for cmd in zpl.split('^FS') if cmd.strip()]

        elements = []

        # Значения размеров этикетки по-умолчанию.
        label_width = 800
        label_height = 600
        dpi = 203  # Низкая детализация.

        # Настройка этикетки.
        if '^PW' in zpl:
            pw_match = re.search(r'\^PW(\d+)', zpl)

            if pw_match:
                label_width = int(pw_match.group(1))

        if '^LL' in zpl:
            ll_match = re.search(r'\^LL(\d+)', zpl)

            if ll_match:
                label_height = int(ll_match.group(1))

        for block in raw_commands:
            if not block:
                continue

            # Обработка GFA отдельно.
            if '^GFA' in block:
                # Извлечение всё связанное до конца.
                gfa_match = re.match(r'\^GFA,\s*(\d+),\s*(\d+),\s*(\d+),\s*([^,]*?)(?=,\s*\^|$)', block)
                if gfa_match:
                    total_bytes, row_bytes, rows, hex_data = gfa_match.groups()


                    # Передаём как есть.
                    fo_match = re.search(r'\^FO\s*(\d+),\s*(\d+)', block)
                    x = int(fo_match.group(1)) if fo_match else 0
                    y = int(fo_match.group(2)) if fo_match else 0

                    elements.append({
                        'type': 'gfa',
                        'x': x,
                        'y': y,
                        'total_bytes': int(total_bytes),
                        'row_bytes': int(row_bytes),
                        'rows': int(rows),
                        'data': hex_data.replace(',', '').replace('::', '')
                    })
                continue

            fo_match = re.search(r'\^FO\s*(\d+),\s*(\d+)', block)
            x = int(fo_match.group(1)) if fo_match else 0
            y = int(fo_match.group(2)) if fo_match else 0

            # Текст.
            if '^FD' in block and '^A' in block:
                fd_match = re.search(r'\^FD\s*(.*?)(?=\^|$)', block)
                text = fd_match.group(1) if fd_match else ''
                a_match = re.search(r'\^A([A-Z0-9@]+)([NRBI]),?\s*(\d*),?\s*(\d*)', block)
                if a_match:
                    font_name = a_match.group(1)
                    rotation = self.rotation_map[a_match.group(2)]
                    height = int(a_match.group(3)) if a_match.group(3) else 30
                    width = int(a_match.group(4)) if a_match.group(4) else 30
                    elements.append({
                        "type": "text",
                        "x": x,
                        "y": y,
                        "text": text,
                        "font": font_name,
                        "rotation": rotation,
                        "height": height,
                        "width": width  # ← передаём в JS
                    })

            elif '^BC' in block:
                bc_match = re.search(r'\^BC([A-Z]),\s*(\d+),\s*([YN]),\s*([YN]),\s*([A-Z]*),?\s*\^FD(.+)', block)
                if bc_match:
                    orientation = bc_match.group(1)
                    height = int(bc_match.group(2))
                    human_readable = bc_match.group(3) == "Y"
                    data = bc_match.group(6).strip()
                    by_match = re.search(r'\^BY\s*(\d+)', block)
                    module_width = int(by_match.group(1)) if by_match else 2
                    elements.append({
                        "type": "barcode",
                        "format": "code128",
                        "x": x,
                        "y": y,
                        "data": data,
                        "height": height,
                        "human_readable": human_readable,
                        "module_width": module_width,
                        "orientation": orientation,
                        "rotation": self.rotation_map.get(orientation, 0)
                    })

            elif '^BQ' in block:
                pass


        return {
            'width': label_width,
            'height': label_height,
            'dpi': dpi,
            'elements': elements
        }


