# helper/network_connections.py

"""Помощник по сетевым подключениям"""

import socketio
import time
import logging

from typing import Optional, Dict, Any, Callable, List
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

class ConnectionStatus(Enum):
    """Статусы подключения"""
    DISCONNECTED = 'disconnected'
    CONNECTING = 'connecting'
    CONNECTED = 'connected'
    ERROR = 'error'
    RECONNECTING = 'reconnecting'

@dataclass
class ConnectionMetrics:
    """Метрики подключения"""
    connected_at: Optional[datetime] = None
    last_ping: Optional[datetime] = None
    lst_pong: Optional[datetime] = None
    ping_count: int = 0
    pong_count: int = 0
    reconnect_attempts: int = 0
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

class SocketIOClient:
    """Клиент для работы с Socket.IO серверами"""

    def __init__(
            self,
            server_url: str,
            auto_reconnect: bool = True,
            reconnection_attempts: int = 5,
            reconnection_delay: int = 1,
            logger: Optional[logging.Logger] = None,
            socketio_options: Optional[Dict[str, Any]] = None
    ):
        """
        :param server_url:  адрес сервера.
        :param auto_reconnect:  Автоматическое переподключение.
        :param reconnection_attempts: Количество попыток подключения.
        :param reconnection_delay: Пауза между попытками (сек).
        :param logger: Логгер для вывода сообщений.
        :param socketio_options: Дополнительные опции для socketio.Client
        """
        self.server_url = server_url
        self.auto_reconnect = auto_reconnect
        self.reconnection_attempts = reconnection_attempts
        self.reconnection_delay = reconnection_delay

        # Логгер.
        self.logger = logger or self._setup_default_logger()

        # Загрузка опций для SOcket.IO
        default_options = {
            'logger': self.logger,
            'engineio_logger': self.logger.level <= logger.DEBUG,
            'reconnection': auto_reconnect,
            'reconnection_attempts': reconnection_attempts,
            'reconnection_delay': reconnection_delay
        }

        if socketio_options:
            default_options.update(socketio_options)

        # Создание клиента.
        self.sio = socketio.Client(**default_options)
        self.status = ConnectionStatus.DISCONNECTED
        self.metric = ConnectionMetrics()

        # Регистрируем базовые обработчики.
        self._register_default_handlers()

        # Хранилище для пользовательских обработчиков.
        self._event_handlers: Dict[str, List[Callable]] = {}

    def _setup_default_logger(self) -> logging.Logger:
        """Настройка логгера по умолчанию"""
        logger = logging.getLogger('SOcketIOClient')
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def _register_default_handlers(self):
        """Регистрация стандартных обработчиков событий"""

        @self.sio.event
        def connect():
            self.status = ConnectionStatus.CONNECTED
            self.metric.connected_at = datetime.now()
            self.logger.info(f'Подключено к {self.server_url}')
            self._trigger_event('connect')

        @self.sio.event
        def connect_error(data):
            self.status = ConnectionStatus.ERROR
            self.logger.error(f'Ошибка подключения: {data}')
            self.metric.errors.append(f'Connect error: {data}')
            self._trigger_event('connect_error', data)

        @self.sio.event
        def disconnect():
            self.status = ConnectionStatus.DISCONNECTED
            self.logger.warning('Отключено от сервера')
            self._trigger_event('disconnect')

            if self.auto_reconnect:
                self.status = ConnectionStatus.RECONNECTING
                self.metric.reconnect_attempts += 1

        @self.sio.on('ping')
        def on_ping(data=None):
            self.metric.last_ping = datetime.now()
            self.metric.ping_count += 1
            self.logger.debug(f'Получен ping: {data}')

            # Автоматический ответ pong.
            self.sio.emit(
                'pong',
                {
                    'response': 'pong',
                    'timestamp': time.time()
                }
            )
            self._trigger_event('ping', data)

        @self.sio.on('pong')
        def on_pong(data=None):
            self.metric.lst_pong = datetime.now()
            self.metric.pong_count += 1
            self.logger.debug(f'Получен pong: {data}')
            self._trigger_event('pong', data)

    def _trigger_event(self, event_name: str, *args, **kwargs):
        """Вызов всех обработчиков для события"""
        if event_name in self._event_handlers:
            for handler in self._event_handlers[event_name]:
                try:
                    handler(*args, **kwargs)
                except Exception as e:
                    self.logger.error(f'Ошибка в обработчике {event_name}: {e}')

    def on(self, event_name: str, handler: Callable):
        """Регистрация обработчика события"""
        if event_name not in self._event_handlers:
            self._event_handlers[event_name] = []

        self._event_handlers[event_name].append(handler)
        self.sio.on(event_name, handler)
        self.logger.debug(f'Зарегистрирован обработчик для события: {event_name}')

        return self

    def off(self, event_name: str, handler: Optional[Callable] = None):
        """Удаление обработчика события"""
        if event_name in self._event_handlers:
            if handler:
                self._event_handlers[event_name].remove(handler)
                if not self._event_handlers[event_name]:
                    del self._event_handlers[event_name]
            else:
                del self._event_handlers[event_name]

            self.sio.on(event_name, lambda *args: None)

        self.logger.debug(f'Удалён обработчик для события: {event_name}')

    def connect(self, timeout: int = 10):
        """Подключение"""
        if self.is_connected():
            self.logger.warning('Уже подключен к серверу')
            return True

        try:
            self.status = ConnectionStatus.CONNECTING
            self.logger.info(f'Подключение к {self.server_url}')

            self.sio.connect(
                self.server_url,
                wait_timeout=timeout,
                wait=True
            )

            return True

        except Exception as e:
            self.status = ConnectionStatus.ERROR
            self.logger.error(f'Ошибка подключения: {e}')
            self.metric.errors.append(str(e))
            return False

    def disconnect(self):
        """Отключение от сервера"""
        if self.is_connected():
            self.sio.disconnect()
            self.logger.info('Отключено от сервера')

    def emit(self, event: str, data: Any = None, callback: Optional[Callable] = None):
        """Отправка события на сервер"""
        if not self.is_connected():
            self.logger.warning('Попытка отправить данные без подключения')
            return False

        try:
            self.sio.emit(event, data, callback=callback)
            self.logger.debug(f'Отправлено событие: {event} : {data}')
            return True
        except Exception as e:
            self.logger.error(f'Ошибка при отправке {event}: {e}')
            return False

    def ping(self, data: Any = None) -> bool:
        """Отправка ping и ожидание pong"""
        if not self.is_connected():
            return False

        result = [False]

        def on_pong_response(response):
            result[0] = True
            self.logger.debug(f'Получен pong: {response}')

        self.sio.event('emit', data, callback=on_pong_response)

        # Ожидание ответа.
        timeout = 5
        start_time = time.time()

        while time.time() - start_time < timeout and not result[0]:
            time.sleep(0.1)
            self.sio.sleep(0)

        return result[0]

    def is_connected(self):
        """Проверка статуса подключения"""
        return self.sio.connected and self.status == ConnectionStatus.CONNECTED

    def get_metrics(self) -> Dict[str, Any]:
        """Получение метрик подключения"""
        return {
            'status': self.status.value,
            'connected': self.is_connected(),
            'connected_at': self.metrics.connected_at,
            'last_ping': self.metrics.last_ping,
            'last_pong': self.metrics.last_pong,
            'ping_count': self.metrics.ping_count,
            'pong_count': self.metrics.pong_count,
            'reconnect_attempts': self.metrics.reconnect_attempts,
            'errors': self.metrics.errors.copy(),
            'sid': getattr(self.sio, 'sid', None)
        }

    def wait(self, seconds: float = None):
        """Ожидание событий"""
        self.sio.wait(seconds)

    def __enter__(self):
        """Поддержка контекстного менеджера"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Автоматическое отключение при выходе из контекста"""
        self.disconnect()

class PrinterSocketClient(SocketIOClient):
    """
    Клиент для работы с принтером.
    """

    def __init__(self, printer_ip: str, port: int = 3000, **kwargs):
        super().__init__(
            server_url=f'http://{printer_ip}:{port}',
            **kwargs
        )

        self._register_default_handlers()

    def _register_printer_handlers(self):
        """Регистрация обработчиков для принтера"""

        @self.on('printer_status')
        def on_printer_status(data):
            """Статус принтера"""
            self.logger.info(f'Статус принтера: {data}')

        @self.on('job_progress')
        def on_job_progress(data):
            """Процесс печати"""
            if data.get('progress'):
                self.logger.info(f'Прогресс: {data["progress"]}')

    def check_availability(self, timeout: int = 5) -> bool:
        """Проверка доступности принтера"""

        if not self.connect(timeout=timeout):
            return False

        is_available = self.ping({'check': 'availability'})

        self.disconnect()
        return is_available

    def get_printer_info(self) -> Optional[Dict[str, Any]]:
        """Получение информации о принтере"""
        if not self.connect():
            return None

        result = [None]

        def on_info_response(data):
            result[0] = data

        self.emit('get_info', callback=on_info_response)

        # Ожидаем ответ.
        timeout = 5
        start_time = time.time()
        while time.time() - start_time < timeout and result[0] is None:
            time.sleep(0.1)
            self.sio.sleep(0)

        self.disconnect()
        return result[0]
