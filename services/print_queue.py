# services/print_queue.py
import asyncio
import logging
import socket
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID
from typing import Callable, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from helpers.printers import (
    check_printer_status, replace_cyrillic_in_zpl, substitute_placeholders, send_zpl_safely)
from models import PrintJob

logger = logging.getLogger(__name__)


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
    retries: int = 0
    max_retries: int = 3
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
            self._cancel_printer_queue(task.printer_ip, task.printer_port)
            logger.info("Задание %s помечено как отменённое", job_id)
            return True
        return False
    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cancel_printer_queue(self, printer_ip: str, printer_port: int) -> bool:
        """Отправить ~JA на принтер — сброс всех заданий в его очереди."""
        try:
            with socket.create_connection((printer_ip, printer_port), timeout=5) as sock:
                sock.sendall(b'~JA')
            logger.info("~JA отправлен на принтер %s:%d", printer_ip, printer_port)
            return True
        except OSError as e:
            logger.warning("Не удалось отправить ~JA на %s:%d: %s", printer_ip, printer_port, e)
            return False

    def _is_cancelled(self, task: PrintTask) -> bool:
        return task.max_retries < 0

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

        for attempt in range(task.max_retries + 1):
            if self._is_cancelled(task):
                await self._mark_job_cancelled(task.job_id, db)
                return

            status = check_printer_status(task.printer_ip, task.printer_port, timeout=2.0)

            if not status.get('ok'):
                wait = 2 ** attempt
                logger.warning("Принтер %s недоступен, ожидание %dс...", printer_addr, wait)
                await asyncio.sleep(wait)
                continue

            if status.get('paused'):
                await self._wait_for_unpause(task, db, printer_addr)
                if self._is_cancelled(task):
                    return

            try:
                await self._print_boxes(task, db, prepared_code, task.printed_count)
                return

            except (socket.timeout, OSError, ConnectionError) as e:
                logger.warning("Ошибка сети при печати %s: %s", job_id_str, e)
                if attempt < task.max_retries and not self._is_cancelled(task):
                    wait = 2 ** attempt
                    logger.info("Повторная попытка через %dс...", wait)
                    await asyncio.sleep(wait)
                else:
                    raise

        raise RuntimeError(
            f"Не удалось выполнить задание {job_id_str} после {task.max_retries + 1} попыток"
        )

    async def _wait_for_unpause(self, task: PrintTask, db: AsyncSession, printer_addr: str):
        """Ждать снятия паузы (до 4 часов)."""
        logger.info("Принтер %s на паузе, ожидание снятия...", printer_addr)
        for _ in range(7200):
            if self._is_cancelled(task):
                await self._mark_job_cancelled(task.job_id, db)
                return
            await asyncio.sleep(2.0)
            status = check_printer_status(task.printer_ip, task.printer_port, timeout=1.0)
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
        with socket.create_connection((task.printer_ip, task.printer_port), timeout=10) as sock:
            # Очистка очереди перед отправкой новых кодов.
            sock.sendall(b'~JA')

            for i in range(start_index, task.boxes_count):
                if self._is_cancelled(task):
                    await self._mark_job_cancelled(task.job_id, db)
                    return

                status = check_printer_status(task.printer_ip, task.printer_port, timeout=1.0)
                if status.get('paused'):
                    raise ConnectionError("Принтер перешёл в паузу во время печати")

                current_box = task.first_box + i
                box_zpl = substitute_placeholders(
                    prepared_code,
                    batch_number=task.batch_number,
                    marking_date=task.marking_date,
                    expiration_date=task.expiration_date,
                    current_box=current_box,
                    gtin=task.gtin,
                )
                send_zpl_safely(sock, box_zpl.encode('utf-8'))

                task.printed_count = i + 1
                job = await db.get(PrintJob, task.job_id)
                if job:
                    job.printed_count = task.printed_count
                    await db.commit()

                await asyncio.sleep(0.1)

        job = await db.get(PrintJob, task.job_id)
        if job:
            job.status = 'completed'
            job.completed_at = datetime.now()
            job.printed_count = task.boxes_count
            await db.commit()
        logger.info("Задание %s успешно завершено", task.job_id)

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
