# services/print_queue.py
import asyncio
import logging
import os
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID
from typing import Callable, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from helpers.printer_drivers import get_driver_or_default
from helpers.printers import (
    check_printer_status_async, check_printer_status_on_socket,
    clear_printer_queue_async,
    replace_cyrillic_in_zpl, substitute_placeholders, send_zpl_safely)
from models import PrintJob

logger = logging.getLogger(__name__)

# Как часто сохранять прогресс печати (printed_count) в БД — этикеток.
PROGRESS_COMMIT_EVERY = 25
# Сколько раз подряд ждать недоступный принтер, прежде чем сдаться.
MAX_UNREACHABLE_WAITS = 60
# Сколько сетевых сбоев подряд при печати допускаем (переподключение), затем отказ.
MAX_RECONNECT_ATTEMPTS = 10

# --- Контроль буфера принтера (запас этикеток в очереди принтера) ---
# Принцип (как с VideoJet: держим запас ~60, проверяем каждую секунду):
# НЕ ждём полного осушения буфера. Как только уровень достигает максимума —
# приостанавливаем отправку, ждём снижения до целевого уровня и продолжаем.
# Так принтер никогда не остаётся без этикеток и при этом не «захлёбывается»
# командами (что лишает его реакции на отмену печати).
BUFFER_CHECK_INTERVAL = 1.0     # как часто проверять уровень буфера, секунд
BUFFER_MAX_LEVEL = 100          # Zebra: форматов в буфере (~HS eee), при которых стоп
BUFFER_TARGET_LEVEL = 60        # Zebra: запас, при котором возобновляем отправку
# Сколько секунд ждать снижения буфера до целевого уровня, прежде чем сдаться.
BUFFER_WAIT_MAX_SECONDS = 60

# TSC (PEX-2340): принтер принимает ТОЛЬКО ОДНО TCP-подключение одновременно
# (проверено эмпирически) — постоянное соединение задания «блокирует» статус
# для страницы контроля. Поэтому TSC отправляет ПАЧКАМИ по task.batch_size,
# каждая пачка — своё подключение (подключился → отправил → закрыл). Между
# пачками принтер свободен: статус работает, очередь может расти без
# блокировок (проверено: 100 этикеток в очереди, статус отвечает).
#
# Контроль очереди — по НАШЕМУ счётчику отправленных и пробегу ~!@ (через
# свежее подключение, между пачками): не отправляем больше task.buffer_limit
# этикеток «впереди» реальной печати. Принтер печатает по сигналам датчика
# линии; остановилась линия — очередь держится на buffer_limit и задание ждёт.
TSC_SEND_TIMEOUT = float(os.getenv('TSC_SEND_TIMEOUT', '4.0'))  # таймаут отправки, сек
TSC_MILEAGE_TIMEOUT = float(os.getenv('TSC_MILEAGE_TIMEOUT', '2.0'))  # запрос пробега, сек
TSC_MILEAGE_POLL = float(os.getenv('TSC_MILEAGE_POLL', '0.5'))   # опрос пробега при ожидании, сек
# Предупреждение, если печать не идёт дольше (и TSC-гейт по пробегу,
# и ZPL-гейт по форматам в буфере).
PRINT_STALL_WARN_SECONDS = 60
# Пауза после очистки очереди перед запросом базового пробега: принтеру нужно
# время обработать <ESC>!.; слишком малая пауза (0.3с) давала сбои — 1с надёжно.
TSC_CLEAR_SETTLE = float(os.getenv('TSC_CLEAR_SETTLE', '1.0'))

# Длина этикетки в дюймах для контроля очереди по пробегу вычисляет драйвер
# TSC (TscDriver.label_length_inches: ^LL + TSC_DPI / TSC_MILEAGE_PER_LABEL).


@dataclass
class PrintTask:
    job_id: UUID
    zpl_code: str
    printer_ip: str
    printer_port: int
    marking_date: any
    expiration_date: any
    batch_number: str
    first_box: int
    boxes_count: int
    gtin: str = ''
    gtin_unit: str = ''
    article: str = ''
    printer_type: str = 'zebra'
    # Контроль очереди принтера (настраивается в карточке принтера):
    # buffer_limit — макс. этикеток «в полёте» без подтверждения статуса,
    # batch_size — пачка отправки между проверками статуса.
    buffer_limit: int = 25
    batch_size: int = 5
    uip_include_batch: bool = True
    # Коды DataMatrix из внешнего сервиса (для шаблонов с is_print_gtin_unit):
    # по одному коду на коробку; подставляются в плейсхолдер {datamatrix}.
    datamatrix_codes: list = field(default_factory=list)
    retries: int = 0
    max_retries: int = 10
    created_at: datetime = field(default_factory=datetime.now)
    printed_count: int = field(default=0, init=False, repr=False)
    # База пробега ~!@ в начале задания (для контроля очереди аппликатора).
    tsc_mileage_start: int = field(default=0, init=False, repr=False)


class PrinterQueue:
    """Асинхронная очередь печати с обработкой пауз и повторами."""

    def __init__(
        self,
        db_getter: Callable[[], AsyncGenerator[AsyncSession, None]],
        max_concurrent_printers: int = 1,
    ):
        self.db_getter = db_getter
        self.queue: asyncio.Queue[PrintTask] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._running = False
        self._max_concurrent = max_concurrent_printers
        self._active_tasks: dict[str, PrintTask] = {}
        # Блокировки по принтерам (ip:port) — задания на один и тот же принтер
        # выполняются строго последовательно, на разные — параллельно.
        self._printer_locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        if self._running:
            return
        self._running = True
        for i in range(self._max_concurrent):
            worker_task = asyncio.create_task(self._worker(f"printer-worker-{i}"))
            self._workers.append(worker_task)
        logger.info("Запущено %d воркеров очереди печати", len(self._workers))

    async def stop(self):
        self._running = False

        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("Очередь печати остановлена")

    async def enqueue(self, task: PrintTask):
        self._active_tasks[str(task.job_id)] = task
        await self.queue.put(task)
        logger.info(
            "Задание %s добавлено в очередь (размер: %d)",
            task.job_id, self.queue.qsize(),
        )

    async def cancel_task(self, job_id: UUID) -> bool:
        """Пометить задание как отменённое и сбросить очередь принтера."""
        task = self._active_tasks.get(str(job_id))
        if task:
            task.max_retries = -1  # флаг отмены
            await self._cancel_printer_queue(
                task.printer_ip, task.printer_port, task.printer_type)
            logger.info("Задание %s помечено как отменённое", job_id)
            return True
        return False
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _cancel_printer_queue(self, printer_ip: str, printer_port: int,
                                    printer_type: str = 'zebra') -> bool:
        """Очистить очередь принтера (Zebra ~JA / TSC CLS).

        Выполняется в отдельном потоке — сетевой вызов не должен блокировать
        event loop (вызывается из веб-роутера отмены задания).
        """
        result = await clear_printer_queue_async(printer_ip, printer_port, printer_type)
        if result.get('success'):
            logger.info("Очередь принтера %s:%d очищена", printer_ip, printer_port)
        else:
            logger.warning(
                "Не удалось очистить очередь принтера %s:%d: %s",
                printer_ip, printer_port, result.get('error'),
            )
        return result.get('success', False)

    def _is_cancelled(self, task: PrintTask) -> bool:
        return task.max_retries < 0

    def _get_printer_lock(self, printer_key: str) -> asyncio.Lock:
        """Блокировка на конкретный принтер (ip:port).

        Гарантирует, что задания на один принтер не перемешают этикетки друг друга,
        при этом задания на разные принтеры могут выполняться параллельно
        (при наличии нескольких воркеров очереди).
        """
        lock = self._printer_locks.get(printer_key)
        if lock is None:
            lock = asyncio.Lock()
            self._printer_locks[printer_key] = lock
        return lock

    async def _get_db(self) -> tuple[AsyncSession, any]:
        gen = self.db_getter()
        db: AsyncSession = await gen.__anext__()
        return db, gen

    @staticmethod
    async def _close_db(db: AsyncSession, gen):
        await db.close()
        await gen.aclose()

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    async def _worker(self, name: str):
        while self._running or not self.queue.empty():
            try:
                task = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            db, gen = None, None
            try:
                printer_key = f"{task.printer_ip}:{task.printer_port}"
                lock = self._get_printer_lock(printer_key)
                async with lock:
                    db, gen = await self._get_db()
                    await self._process_task(task, db)
            except asyncio.CancelledError:
                self.queue.put_nowait(task)
                raise
            except Exception as e:
                logger.exception("Ошибка в воркере %s при обработке %s: %s", name, task.job_id, e)
                if task.retries < task.max_retries and not self._is_cancelled(task):
                    task.retries += 1
                    task.created_at = datetime.now()
                    await self.queue.put(task)
                    logger.warning(
                        "Задание %s возвращено в очередь (попытка %d)",
                        task.job_id, task.retries,
                    )
                else:
                    await self._mark_job_failed(task.job_id, str(e), task.printed_count)
            finally:
                if db is not None:
                    await self._close_db(db, gen)
                self._active_tasks.pop(str(task.job_id), None)
                self.queue.task_done()

    # ------------------------------------------------------------------
    # Core task processing
    # ------------------------------------------------------------------

    async def _process_task(self, task: PrintTask, db: AsyncSession):
        job_id_str = str(task.job_id)
        printer_addr = f"{task.printer_ip}:{task.printer_port}"

        job = await db.get(PrintJob, task.job_id)
        if not job:
            logger.error("Задание %s не найдено в БД", job_id_str)
            return

        job.status = 'processing'
        job.printed_count = task.printed_count
        await db.commit()

        prepared_code = replace_cyrillic_in_zpl(task.zpl_code)

        # Печать, устойчивая к нестабильной сети:
        #  - принтер недоступен — ждём с растущим backoff (не «убиваем» задание
        #    через пару секунд), затем продолжаем;
        #  - обрыв при печати — создаём новое подключение и продолжаем с места
        #    остановки (task.printed_count хранится в памяти и точен).
        unreachable_waits = 0
        reconnect_count = 0

        while True:
            if self._is_cancelled(task):
                await self._mark_job_cancelled(task.job_id, db, task.printed_count)
                return

            status = await check_printer_status_async(
                task.printer_ip, task.printer_port, task.printer_type,
                timeout=2.0
            )

            if not status.get('ok'):
                # Принтер/сеть недоступны — ждём, не расходуя попыток печати.
                reconnect_count = 0
                unreachable_waits += 1
                if unreachable_waits > MAX_UNREACHABLE_WAITS:
                    raise RuntimeError(
                        f"Принтер {printer_addr} недоступен слишком долго "
                        f"(ждём более {MAX_UNREACHABLE_WAITS} интервалов)"
                    )
                wait = min(2 ** (unreachable_waits - 1), 30)
                logger.warning(
                    "Принтер %s недоступен, повтор через %dс (ожидание %d)...",
                    printer_addr, wait, unreachable_waits,
                )
                await asyncio.sleep(wait)
                continue

            unreachable_waits = 0

            if status.get('paused'):
                await self._wait_for_unpause(task, db, printer_addr)
                if self._is_cancelled(task):
                    return
                continue

            try:
                await self._print_boxes(task, db, prepared_code, task.printed_count)
                return

            except (socket.timeout, OSError, ConnectionError) as e:
                # Обрыв соединения при печати — переподключаемся и продолжаем.
                reconnect_count += 1
                if self._is_cancelled(task):
                    await self._mark_job_cancelled(task.job_id, db, task.printed_count)
                    return
                if reconnect_count > MAX_RECONNECT_ATTEMPTS:
                    raise RuntimeError(
                        f"Задание {job_id_str}: {MAX_RECONNECT_ATTEMPTS + 1} "
                        f"сетевых сбоев подряд, печать прервана"
                    ) from e
                wait = min(2 ** reconnect_count, 30)
                logger.warning(
                    "Сетевая ошибка при печати %s (повтор %d): %s. "
                    "Новое подключение через %dс...",
                    job_id_str, reconnect_count, e, wait,
                )
                await asyncio.sleep(wait)

    async def _wait_for_unpause(self, task: PrintTask, db: AsyncSession, printer_addr: str):
        """Ждать снятия паузы (до 4 часов)."""
        logger.info("Принтер %s на паузе, ожидание снятия...", printer_addr)
        for _ in range(7200):
            if self._is_cancelled(task):
                await self._mark_job_cancelled(task.job_id, db, task.printed_count)
                return
            await asyncio.sleep(2.0)
            status = await check_printer_status_async(
                task.printer_ip, task.printer_port, task.printer_type,
                timeout=1.0
            )
            if status.get('ok') and not status.get('paused'):
                logger.info("Принтер %s возобновил работу", printer_addr)
                return
        raise TimeoutError(f"Принтер {printer_addr} не вышел из паузы за 4 часа")

    async def _print_boxes(
        self,
        task: PrintTask,
        db: AsyncSession,
        prepared_code: str,
        start_index: int,
    ):
        """Отправить ящики на принтер, начиная с start_index."""
        # Задание загружаем один раз — в цикле обновляем только printed_count.
        job = await db.get(PrintJob, task.job_id)
        if not job:
            logger.error("Задание %s не найдено в БД при печати", task.job_id)
            return

        # Поведение, специфичное для типа принтера, определяется драйвером
        # (helpers/printer_drivers.py):
        #   * batch_send     — пачечная отправка: каждая пачка своим
        #                      TCP-подключением. Для TSC это требование
        #                      (одно соединение одновременно), для ZPL —
        #                      ограничение очереди (не «заливать» медленный
        #                      принтер больше, чем на buffer_limit этикеток);
        #   * mileage_gate   — контроль очереди по пробегу (аппликаторы TSC);
        #   * buffer_control — контроль очереди по числу форматов (~HS, ZPL)
        #                      или флагу переполнения (TSC).
        driver = get_driver_or_default(task.printer_type)
        batch_mode = driver.batch_send

        # Очистка очереди принтера (команда из драйвера) — только при начале
        # задания (start_index == 0). При переподключении после сетевого сбоя
        # печать продолжается БЕЗ очистки, иначе теряются уже отправленные,
        # но ещё не напечатанные этикетки.

        # Сеть — блокирующие операции выполняем в отдельном потоке, чтобы
        # длительный connect/отправка не «замораживали» event loop (веб).
        # Пачечные драйверы (TSC, ZPL) каждую пачку отправляют СВОИМ
        # подключением — между пачками принтер свободен и отвечает на запросы
        # статуса/пробега. Непрерывные драйверы (если появятся) держат
        # постоянное соединение.
        sock = None
        if not batch_mode:
            sock = await asyncio.to_thread(
                socket.create_connection,
                (task.printer_ip, task.printer_port), 10,
            )
        try:
            if start_index == 0:
                if batch_mode:
                    # Очистка очереди отдельным коротким подключением.
                    await clear_printer_queue_async(
                        task.printer_ip, task.printer_port, task.printer_type)
                    # Даём принтеру обработать очистку (0.3с мало — 1с надёжно).
                    await asyncio.sleep(TSC_CLEAR_SETTLE)
                    # База пробега — свежее подключение работает.
                    if driver.mileage_gate:
                        for _attempt in range(3):
                            task.tsc_mileage_start = await asyncio.to_thread(
                                driver.mileage,
                                task.printer_ip, task.printer_port,
                                TSC_MILEAGE_TIMEOUT) or 0
                            if task.tsc_mileage_start:
                                break
                            await asyncio.sleep(1)
                        if not task.tsc_mileage_start:
                            logger.warning(
                                "%s %s:%d: не удалось получить базовый пробег — "
                                "контроль очереди по пробегу отключён",
                                driver.label, task.printer_ip, task.printer_port,
                            )
                else:
                    await asyncio.to_thread(sock.sendall, driver.clear_cmd)
            else:
                logger.info(
                    "Задание %s: докачка с коробки %d без очистки очереди принтера",
                    task.job_id, task.first_box + start_index,
                )

            last_buffer_check = time.monotonic() - BUFFER_CHECK_INTERVAL
            batch_conn = None
            labels_in_batch = 0
            label_inches = None
            if driver.mileage_gate:
                label_inches = driver.label_length_inches(prepared_code)
                if label_inches is None:
                    logger.warning(
                        "%s %s:%d: не удалось вычислить длину этикетки (нет ^LL / "
                        "TSC_MILEAGE_PER_LABEL) — гейт очереди отключён",
                        driver.label, task.printer_ip, task.printer_port,
                    )

            for i in range(start_index, task.boxes_count):
                if self._is_cancelled(task):
                    await self._mark_job_cancelled(task.job_id, db, task.printed_count)
                    return

                if batch_mode:
                    if batch_conn is None:
                        # Начало новой пачки. Гейт очереди выполняется ТОЛЬКО
                        # здесь — когда соединение принтера закрыто (опрос
                        # статуса/пробега возможен только между пачками).
                        # Не отправляем больше buffer_limit этикеток «впереди»
                        # реальной печати: TSC — по пробегу (~!@),
                        # ZPL — по числу форматов в буфере (~HS eee).
                        await self._wait_for_batch_gate(task, i, driver, label_inches)
                        # Пачка: своё подключение на batch_size этикеток.
                        batch_conn = await asyncio.to_thread(
                            socket.create_connection,
                            (task.printer_ip, task.printer_port), 10)
                        batch_conn.settimeout(TSC_SEND_TIMEOUT)
                        labels_in_batch = 0
                else:
                    # Непрерывный режим (драйверы без batch_send): контроль
                    # буфера по числу форматов (~HS eee) раз в секунду.
                    now = time.monotonic()
                    if now - last_buffer_check >= BUFFER_CHECK_INTERVAL:
                        last_buffer_check = now
                        await self._control_printer_buffer(task, sock)

                current_box = task.first_box + i
                box_zpl = substitute_placeholders(
                    prepared_code,
                    batch_number=task.batch_number,
                    marking_date=task.marking_date,
                    expiration_date=task.expiration_date,
                    current_box=current_box,
                    gtin=task.gtin,
                    gtin_unit=task.gtin_unit,
                    article=task.article,
                    uip_include_batch=task.uip_include_batch,
                    datamatrix=(
                        task.datamatrix_codes[i]
                        if i < len(task.datamatrix_codes) else ''
                    ),
                )
                label_bytes = box_zpl.encode('utf-8')
                await asyncio.to_thread(
                    send_zpl_safely, batch_conn if batch_mode else sock, label_bytes)

                if batch_mode:
                    labels_in_batch += 1
                    if labels_in_batch >= max(1, task.batch_size):
                        # Пачка отправлена — закрываем соединение (принтер свободен).
                        await asyncio.to_thread(batch_conn.close)
                        batch_conn = None
                        # Между пачками: пауза/ошибка принтера (свежее подключение
                        # работает, принтер свободен).
                        if not await self._try_printer_status(task, None):
                            await self._wait_for_printer_status(task, None)

                task.printed_count = i + 1
                job.printed_count = task.printed_count

                # Прогресс в БД: для пачечных драйверов коммитим РАЗ В ПАЧКУ
                # (каждые batch_size этикеток) — гейт ограничивает очередь
                # буфером, и счётчик должен обновляться в пределах пачки.
                # Для непрерывных — пакетно каждые PROGRESS_COMMIT_EVERY.
                if batch_mode:
                    if (i + 1) % max(1, task.batch_size) == 0:
                        await db.commit()
                elif (i + 1) % PROGRESS_COMMIT_EVERY == 0:
                    await db.commit()

                if not batch_mode:
                    await asyncio.sleep(0.1)
        finally:
            if sock is not None:
                await asyncio.to_thread(sock.close)
            if batch_conn is not None:
                await asyncio.to_thread(batch_conn.close)

        job.status = 'completed'
        job.completed_at = datetime.now()
        job.printed_count = task.boxes_count
        await db.commit()
        logger.info("Задание %s успешно завершено", task.job_id)

    async def _query_status(self, task: PrintTask, sock, timeout: float = 1.0) -> dict:
        """Статус принтера: по рабочему сокету (во время печати) или через
        отдельное подключение (до/после печати). Не блокирует event loop."""
        if sock is not None:
            return await asyncio.to_thread(
                check_printer_status_on_socket, sock, task.printer_type, timeout)
        return await check_printer_status_async(
            task.printer_ip, task.printer_port, task.printer_type, timeout=timeout)

    async def _try_printer_status(self, task: PrintTask, sock) -> bool:
        """Один запрос статуса: True — принтер доступен (буфер в норме).

        Пауза останавливает печать (ConnectionError -> внешний цикл ждёт
        снятия паузы); ошибка принтера/недоступность — False (не шлём).
        """
        status = await self._query_status(task, sock, timeout=1.0)
        if not status.get('ok'):
            return False
        if status.get('paused'):
            raise ConnectionError("Принтер перешёл в паузу во время печати")
        if status.get('error_flag'):
            return False
        return True

    async def _wait_for_printer_status(self, task: PrintTask, sock):
        """Ждать, пока принтер снова подтвердит доступность (очередь
        освободилась — допечатал). При остановке линии ждём без ошибок."""
        printer_addr = f"{task.printer_ip}:{task.printer_port}"
        warned = False
        while True:
            if self._is_cancelled(task):
                raise ConnectionError("Задание отменено при ожидании принтера")
            try:
                if await self._try_printer_status(task, sock):
                    return
            except ConnectionError:
                raise
            if not warned:
                warned = True
                logger.warning(
                    "Принтер %s не подтверждает статус (очередь принтера заполнена) — "
                    "отправка приостановлена, ждём освобождения",
                    printer_addr,
                )
            await asyncio.sleep(1.0)

    async def _wait_for_label_consumption(self, task: PrintTask, i: int,
                                          label_inches: float):
        """Аппликатор TSC: гейт очереди по пробегу ~!@ (в начале пачки).

        Перед отправкой пачки из task.batch_size этикеток ждём, пока очередь
        принтера (отправлено − напечатано по пробегу) после пачки не превысит
        task.buffer_limit. Принтер печатает по сигналам датчика линии;
        остановилась линия — ждём.

        Пробег запрашивается СВЕЖИМ подключением (между пачками принтер
        свободен; внутри пачки соединение занято и запросы не работают —
        поэтому метод вызывается только при batch_conn is None).
        """
        printer_addr = f"{task.printer_ip}:{task.printer_port}"
        driver = get_driver_or_default(task.printer_type)
        batch_size = max(1, task.batch_size)
        required_printed = max(0, i + batch_size - max(1, task.buffer_limit))
        stall_warned = False
        stall_since = time.monotonic()

        while True:
            if self._is_cancelled(task):
                raise ConnectionError("Задание отменено при ожидании печати аппликатора")

            m = await asyncio.to_thread(
                driver.mileage,
                task.printer_ip, task.printer_port, TSC_MILEAGE_TIMEOUT)
            if m is None:
                # Пробег не узнать (принтер занят) — ждём и пробуем снова.
                # Статус-гейт между пачками остановит при реальном зависании.
                await asyncio.sleep(TSC_MILEAGE_POLL)
                continue

            printed = (m - (task.tsc_mileage_start or m)) / label_inches
            if printed >= required_printed:
                return

            if not stall_warned and time.monotonic() - stall_since > PRINT_STALL_WARN_SECONDS:
                stall_warned = True
                logger.warning(
                    "Принтер %s (аппликатор) не печатает уже %dс — очередь заполнена "
                    "(отправлено %d, напечатано ~%d). Жду сигнала датчика линии",
                    printer_addr, PRINT_STALL_WARN_SECONDS, i, int(printed),
                )
            await asyncio.sleep(TSC_MILEAGE_POLL)

    async def _wait_for_batch_gate(self, task: PrintTask, i: int, driver, label_inches):
        """Гейт очереди перед пачкой: не отправлять больше buffer_limit
        этикеток «впереди» реальной печати.

        Метод зависит от возможностей драйвера:
          * mileage_gate        (TSC) — контроль по пробегу печати (~!@);
          * buffer_control == 'formats' (ZPL/Zebra) — по числу форматов
            в буфере принтера (~HS eee).
        """
        if driver.mileage_gate:
            if label_inches and task.tsc_mileage_start:
                await self._wait_for_label_consumption(task, i, label_inches)
        elif driver.buffer_control == 'formats':
            await self._wait_for_formats_consumption(task, i)

    async def _wait_for_formats_consumption(self, task: PrintTask, i: int):
        """ZPL/Zebra: гейт очереди по числу форматов в буфере (~HS eee).

        Перед отправкой пачки ждём, пока «впереди» реальной печати останется
        не больше buffer_limit − batch_size форматов — тогда после отправки
        пачки в очереди принтера будет не больше buffer_limit этикеток.
        Принтер может печатать медленно: ждём столько, сколько нужно, и не
        «заливаем» его очередями (как TSC по пробегу — здесь по ~HS).

        Уровень запрашивается СВЕЖИМ подключением (между пачками принтер
        свободен; внутри пачки соединение занято — поэтому метод вызывается
        только при batch_conn is None).
        """
        printer_addr = f"{task.printer_ip}:{task.printer_port}"
        batch_size = max(1, task.batch_size)
        buffer_limit = max(1, task.buffer_limit)
        max_ahead = max(0, buffer_limit - batch_size)
        stall_warned = False
        stall_since = time.monotonic()

        while True:
            if self._is_cancelled(task):
                raise ConnectionError("Задание отменено при ожидании печати")

            status = await check_printer_status_async(
                task.printer_ip, task.printer_port, task.printer_type, timeout=1.0,
            )
            if not status.get('ok'):
                # Принтер/сеть недоступны — ждём и пробуем снова.
                await asyncio.sleep(BUFFER_CHECK_INTERVAL)
                continue
            if status.get('paused'):
                raise ConnectionError("Принтер перешёл в паузу во время печати")

            level_raw = status.get('formats_in_buffer', '0')
            if level_raw in ('?', '', None):
                # Уровень буфера недоступен — гейт отключается (печатаем пачками
                # без ограничения, как раньше).
                return
            level = int(level_raw)
            if level <= max_ahead:
                return

            if not stall_warned and time.monotonic() - stall_since > PRINT_STALL_WARN_SECONDS:
                stall_warned = True
                logger.warning(
                    "Принтер %s не печатает уже %dс — в очереди принтера %d этикеток "
                    "(лимит %d). Жду освобождения (принтер может печатать медленно)",
                    printer_addr, PRINT_STALL_WARN_SECONDS, level, buffer_limit,
                )
            await asyncio.sleep(BUFFER_CHECK_INTERVAL)

    async def _control_printer_buffer(self, task: PrintTask, sock=None):
        """Проверка статуса принтера и поддержание запаса в его буфере.

        Zebra — уровень форматов в буфере (~HS eee): стоп при
        BUFFER_MAX_LEVEL (или флаге переполнения), продолжение — когда
        уровень ниже BUFFER_TARGET_LEVEL.

        TSC во время печати запросы не обрабатывает (см. константы TSC_*) —
        контроль для него темповая отправка в _print_boxes, сюда не заходит.

        При печати (sock передан) статус запрашивается ПО ТОМУ ЖЕ СОКЕТУ.
        """
        printer_addr = f"{task.printer_ip}:{task.printer_port}"

        status = await self._query_status(task, sock, timeout=1.0)

        if not status.get('ok'):
            # Сбой статуса не останавливает печать (следующая отправка сама
            # выявит обрыв). Логируем только при смене ошибки, чтобы не
            # засорять консоль одинаковыми сообщениями каждую секунду.
            error = status.get('error') or 'Unknown'
            if getattr(task, '_last_buffer_error', None) != error:
                logger.warning(
                    "Не удалось получить статус принтера %s при контроле буфера: %s",
                    printer_addr, error,
                )
                task._last_buffer_error = error
            return
        task._last_buffer_error = None

        if status.get('paused'):
            raise ConnectionError("Принтер перешёл в паузу во время печати")

        # Общий путь: флаг переполнения / количество форматов (Zebra).
        level_raw = status.get('formats_in_buffer', '0')
        level = int(level_raw) if level_raw not in ('?', '', None) else 0
        too_full = bool(status.get('buffer_full')) or (level >= BUFFER_MAX_LEVEL and level > 0)
        if not too_full:
            return

        logger.warning(
            "Буфер принтера %s заполнен (форматов: %s, флаг full: %s). "
            "Ждём снижения до %d, чтобы оставить запас этикеток...",
            printer_addr, level_raw, status.get('buffer_full'), BUFFER_TARGET_LEVEL,
        )
        await self._wait_for_buffer_reserve(task, printer_addr, sock)

    async def _wait_for_buffer_reserve(self, task: PrintTask, printer_addr: str, sock=None):
        """Ждать, пока буфер принтера снизится до целевого уровня запаса.

        Возобновляем отправку, не дожидаясь полного осушения:
          Zebra — уровень форматов упал ниже BUFFER_TARGET_LEVEL;
          TSC   — флаг переполнения снят.
        """
        for _ in range(int(BUFFER_WAIT_MAX_SECONDS / BUFFER_CHECK_INTERVAL)):
            if self._is_cancelled(task):
                raise ConnectionError("Задание отменено при ожидании освобождения буфера")
            await asyncio.sleep(BUFFER_CHECK_INTERVAL)

            status = await self._query_status(task, sock, timeout=1.0)
            if not status.get('ok'):
                # Сбой сети при ожидании — пусть внешний цикл переподключения
                # разберётся с соединением.
                raise ConnectionError(
                    f"Не удалось получить статус принтера {printer_addr}: "
                    f"{status.get('error')}"
                )
            if status.get('paused'):
                raise ConnectionError("Принтер перешёл в паузу во время печати")

            if status.get('buffer_full'):
                continue  # буфер всё ещё заполнен

            if get_driver_or_default(task.printer_type).buffer_control == 'full_flag':
                logger.info("Буфер принтера %s освободился, продолжаем", printer_addr)
                return

            level_raw = status.get('formats_in_buffer', '0')
            level = int(level_raw) if level_raw not in ('?', '', None) else 0
            if level < BUFFER_TARGET_LEVEL:
                logger.info(
                    "Буфер принтера %s: осталось %d форматов, продолжаем",
                    printer_addr, level,
                )
                return

        raise ConnectionError(
            f"Буфер принтера {printer_addr} не снижается до целевого уровня "
            f"({BUFFER_TARGET_LEVEL}) за {BUFFER_WAIT_MAX_SECONDS}с"
        )

    # ------------------------------------------------------------------
    # DB status helpers
    # ------------------------------------------------------------------

    async def _mark_job_failed(self, job_id: UUID, error: str, printed_count: int = 0):
        try:
            db, gen = await self._get_db()
            job = await db.get(PrintJob, job_id)
            if job:
                job.status = 'failed'
                job.error_message = error[:500]
                job.printed_count = printed_count
                await db.commit()
            await self._close_db(db, gen)
        except Exception as e:
            logger.error("Не удалось обновить статус задания %s: %s", job_id, e)

    async def _mark_job_cancelled(self, job_id: UUID, db: AsyncSession,
                                  printed_count: int = 0):
        job = await db.get(PrintJob, job_id)
        if job:
            job.status = 'cancelled'
            job.error_message = 'Остановлено оператором'
            if printed_count:
                job.printed_count = printed_count
            await db.commit()
        logger.info("Задание %s отменено", job_id)
