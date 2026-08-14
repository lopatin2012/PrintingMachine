# services/print_queue.py
import asyncio
import logging
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID
from typing import Callable, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from helpers.printers import (
    check_printer_status_by_type, clear_printer_queue, replace_cyrillic_in_zpl,
    substitute_placeholders, send_zpl_safely)
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

# Количество этикеток в буфере TSC с хоста не запрашивается (см. docstring
# check_printer_status_tsc) — контроль для TSC бинарный, по флагу
# «Receive buffer full» из <ESC>!S: стоп при переполнении, продолжение —
# когда флаг снят.


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
    uip_include_batch: bool = True
    retries: int = 0
    max_retries: int = 10
    created_at: datetime = field(default_factory=datetime.now)
    printed_count: int = field(default=0, init=False, repr=False)


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

    def cancel_task(self, job_id: UUID) -> bool:
        """Пометить задание как отменённое и сбросить очередь принтера."""
        task = self._active_tasks.get(str(job_id))
        if task:
            task.max_retries = -1  # флаг отмены
            self._cancel_printer_queue(
                task.printer_ip, task.printer_port, task.printer_type)
            logger.info("Задание %s помечено как отменённое", job_id)
            return True
        return False
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cancel_printer_queue(self, printer_ip: str, printer_port: int,
                              printer_type: str = 'zebra') -> bool:
        """Очистить очередь принтера (Zebra ~JA / TSC CLS)."""
        result = clear_printer_queue(printer_ip, printer_port, printer_type)
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
                await self._mark_job_cancelled(task.job_id, db)
                return

            status = check_printer_status_by_type(
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
                    await self._mark_job_cancelled(task.job_id, db)
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
                await self._mark_job_cancelled(task.job_id, db)
                return
            await asyncio.sleep(2.0)
            status = check_printer_status_by_type(
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

        # Очистка очереди принтера (Zebra ~JA / TSC CLS) — только при начале
        # задания (start_index == 0). При переподключении после сетевого сбоя
        # печать продолжается БЕЗ очистки, иначе теряются уже отправленные,
        # но ещё не напечатанные этикетки.
        clear_cmd = b'CLS\r\n' if (task.printer_type or '').lower() == 'tsc' else b'~JA'

        with socket.create_connection((task.printer_ip, task.printer_port), timeout=10) as sock:
            if start_index == 0:
                sock.sendall(clear_cmd)
            else:
                logger.info(
                    "Задание %s: докачка с коробки %d без очистки очереди принтера",
                    task.job_id, task.first_box + start_index,
                )

            # Контроль статуса и буфера — раз в BUFFER_CHECK_INTERVAL по времени
            # (не по числу этикеток: принтер печатает с переменной скоростью).
            last_buffer_check = time.monotonic() - BUFFER_CHECK_INTERVAL
            for i in range(start_index, task.boxes_count):
                if self._is_cancelled(task):
                    await self._mark_job_cancelled(task.job_id, db)
                    return

                now = time.monotonic()
                if now - last_buffer_check >= BUFFER_CHECK_INTERVAL:
                    last_buffer_check = now
                    await self._control_printer_buffer(task)

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
                )
                send_zpl_safely(sock, box_zpl.encode('utf-8'))

                task.printed_count = i + 1
                job.printed_count = task.printed_count

                # Прогресс в БД сохраняем пакетно, а не на каждую этикетку
                # (printed_count в памяти точный — докачка после сбоя идёт с него).
                if (i + 1) % PROGRESS_COMMIT_EVERY == 0:
                    await db.commit()

                await asyncio.sleep(0.1)

        job.status = 'completed'
        job.completed_at = datetime.now()
        job.printed_count = task.boxes_count
        await db.commit()
        logger.info("Задание %s успешно завершено", task.job_id)

    async def _control_printer_buffer(self, task: PrintTask):
        """Проверка статуса принтера и поддержание запаса в его буфере.

        Не дожидаемся полной очистки буфера — держим запас этикеток:
          Zebra — уровень форматов в буфере (~HS eee): стоп при
                  BUFFER_MAX_LEVEL (или флаге переполнения), продолжение —
                  когда уровень ниже BUFFER_TARGET_LEVEL;
          TSC   — флаг «Receive buffer full» (<ESC>!S): стоп при переполнении,
                  продолжение — когда флаг снят (количество недоступно).
        """
        printer_addr = f"{task.printer_ip}:{task.printer_port}"
        status = check_printer_status_by_type(
            task.printer_ip, task.printer_port, task.printer_type,
            timeout=1.0,
        )

        if not status.get('ok'):
            # Статус не получен (сбой сети) — не останавливаем печать здесь:
            # следующая отправка этикетки сама выявит обрыв и включит
            # переподключение.
            logger.warning(
                "Не удалось получить статус принтера %s при контроле буфера: %s",
                printer_addr, status.get('error'),
            )
            return

        if status.get('paused'):
            raise ConnectionError("Принтер перешёл в паузу во время печати")

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
        await self._wait_for_buffer_reserve(task, printer_addr)

    async def _wait_for_buffer_reserve(self, task: PrintTask, printer_addr: str):
        """Ждать, пока буфер принтера снизится до целевого уровня запаса.

        Возобновляем отправку, не дожидаясь полного осушения:
          Zebra — уровень форматов упал ниже BUFFER_TARGET_LEVEL;
          TSC   — флаг переполнения снят.
        """
        for _ in range(int(BUFFER_WAIT_MAX_SECONDS / BUFFER_CHECK_INTERVAL)):
            if self._is_cancelled(task):
                raise ConnectionError("Задание отменено при ожидании освобождения буфера")
            await asyncio.sleep(BUFFER_CHECK_INTERVAL)

            status = check_printer_status_by_type(
                task.printer_ip, task.printer_port, task.printer_type,
                timeout=1.0,
            )
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

            if (task.printer_type or '').lower() == 'tsc':
                logger.info("Буфер принтера %s освободился (TSC), продолжаем", printer_addr)
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

    async def _mark_job_cancelled(self, job_id: UUID, db: AsyncSession):
        job = await db.get(PrintJob, job_id)
        if job:
            job.status = 'cancelled'
            job.error_message = 'Остановлено оператором'
            await db.commit()
        logger.info("Задание %s отменено", job_id)
