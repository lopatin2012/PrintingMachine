# services/print_queue.py
import asyncio
import logging
import socket
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID
from typing import Optional, Callable, AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

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


class PrinterQueue:
    """Асинхронная очередь печати с обработкой пауз и повторами."""

    def __init__(self, db_getter: Callable[[], AsyncGenerator[AsyncSession, None]],
                 max_concurrent_printers: int = 1):
        self.db_getter = db_getter
        self.queue: asyncio.Queue[PrintTask] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._running = False
        self._max_concurrent = max_concurrent_printers
        # Реестр активных заданий для отмены: job_id → PrintTask
        self._active_tasks: dict[str, PrintTask] = {}

    async def start(self):
        if self._running:
            return
        self._running = True
        for i in range(self._max_concurrent):
            task = asyncio.create_task(self._worker(f"printer-worker-{i}"))
            self._workers.append(task)
        logger.info(f"Запущено {len(self._workers)} воркеров очереди печати")

    async def stop(self):
        self._running = False
        await self.queue.join()
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("Очередь печати остановлена")

    async def enqueue(self, task: PrintTask):
        self._active_tasks[str(task.job_id)] = task
        await self.queue.put(task)
        logger.info(f"Задание {task.job_id} добавлено в очередь (размер: {self.queue.qsize()})")

    def cancel_task(self, job_id: UUID) -> bool:
        """Отметить задание как отменённое (проверяется в _process_task)."""
        job_id_str = str(job_id)
        task = self._active_tasks.get(job_id_str)
        if task:
            task.max_retries = -1  # Флаг отмены: любая ошибка прервёт выполнение
            logger.info(f"Задание {job_id_str} помечено как отменённое")
            return True
        return False

    async def _worker(self, name: str):
        from helpers.printers import check_printer_status

        while self._running or not self.queue.empty():
            try:
                task = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            try:
                # Получаем сессию БД
                db_gen = self.db_getter()
                db: AsyncSession = await db_gen.__anext__()

                await self._process_task(task, db)

                await db.close()
                await db_gen.aclose()
                self.queue.task_done()

            except asyncio.CancelledError:
                self.queue.put_nowait(task)
                raise
            except Exception as e:
                logger.exception(f"Ошибка в воркере {name} при обработке {task.job_id}: {e}")
                if task.retries < task.max_retries and task.max_retries >= 0:
                    task.retries += 1
                    task.created_at = datetime.now()
                    await self.queue.put(task)
                    logger.warning(f"Задание {task.job_id} возвращено в очередь (попытка {task.retries})")
                else:
                    # Финальная ошибка — обновляем статус в БД
                    await self._mark_job_failed(task.job_id, str(e))
                self.queue.task_done()
            finally:
                # Удаляем из активных, если задание завершено
                if task.job_id in self._active_tasks:
                    del self._active_tasks[str(task.job_id)]

    async def _process_task(self, task: PrintTask, db: AsyncSession):
        from helpers.printers import check_printer_status
        from helpers.printers import substitute_placeholders, replace_cyrillic_in_zpl, send_zpl_safely
        from models import PrintJob

        job_id_str = str(task.job_id)
        printer_addr = f"{task.printer_ip}:{task.printer_port}"

        # Обновляем статус в БД
        job = await db.get(PrintJob, task.job_id)
        if not job:
            logger.error(f"Задание {job_id_str} не найдено в БД")
            return
        job.status = 'processing'
        job.printed_count = 0
        await db.commit()

        prepared_code = replace_cyrillic_in_zpl(task.zpl_code)

        for attempt in range(task.max_retries + 1):
            # Проверяем флаг отмены
            if task.max_retries < 0:
                await self._mark_job_cancelled(task.job_id, db)
                return

            status = check_printer_status(task.printer_ip, task.printer_port, timeout=2.0)

            if not status.get('ok'):
                wait = 2 ** attempt
                logger.warning(f"Принтер {printer_addr} недоступен, ожидание {wait}с...")
                await asyncio.sleep(wait)
                continue

            if status.get('paused'):
                logger.info(f"Принтер {printer_addr} на паузе, ожидание снятия...")
                for _ in range(7200):  # ~4 часа
                    if task.max_retries < 0:  # Проверка отмены внутри ожидания
                        await self._mark_job_cancelled(task.job_id, db)
                        return
                    await asyncio.sleep(2.0)
                    status = check_printer_status(task.printer_ip, task.printer_port, timeout=1.0)
                    if status.get('ok') and not status.get('paused'):
                        break
                else:
                    raise TimeoutError(f"Принтер {printer_addr} не вышел из паузы за 4 часа")

            # Принтер готов — печать
            try:
                with socket.create_connection((task.printer_ip, task.printer_port), timeout=10) as sock:
                    for i in range(task.boxes_count):
                        # Проверка отмены перед каждой этикеткой
                        if task.max_retries < 0:
                            await self._mark_job_cancelled(task.job_id, db)
                            return

                        # Проверка паузы
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
                            gtin=task.gtin
                        )

                        send_zpl_safely(sock, box_zpl.encode('utf-8'))

                        # Обновление прогресса
                        job = await db.get(PrintJob, task.job_id)
                        if job:
                            job.printed_count = i + 1
                            await db.commit()

                        await asyncio.sleep(0.1)

                # Успех!
                job = await db.get(PrintJob, task.job_id)
                if job:
                    job.status = 'completed'
                    job.completed_at = datetime.utcnow()
                    job.printed_count = task.boxes_count
                    await db.commit()
                logger.info(f"Задание {job_id_str} успешно завершено")
                return  # ← Ключевой return! Не даём выполниться коду ниже

            except (socket.timeout, OSError, ConnectionError) as e:
                logger.warning(f"Ошибка сети при печати {job_id_str}: {e}")
                if attempt < task.max_retries and task.max_retries >= 0:
                    wait = 2 ** attempt
                    logger.info(f"Повторная попытка через {wait}с...")
                    await asyncio.sleep(wait)
                else:
                    raise

         # Если цикл завершился без return — все попытки исчерпаны
        raise RuntimeError(f"Не удалось выполнить задание {job_id_str} после {task.max_retries + 1} попыток")

    async def _mark_job_failed(self, job_id: UUID, error: str):
        """Вспомогательный метод: пометить задание как failed."""
        try:
            db_gen = self.db_getter()
            db = await db_gen.__anext__()
            job = await db.get(PrintJob, job_id)
            if job:
                job.status = 'failed'
                job.error_message = error[:500]
                await db.commit()
            await db.close()
            await db_gen.aclose()
        except Exception as e:
            logger.error(f"Не удалось обновить статус задания {job_id}: {e}")

    async def _mark_job_cancelled(self, job_id: UUID, db: AsyncSession):
        """Пометить задание как cancelled."""
        job = await db.get(PrintJob, job_id)
        if job:
            job.status = 'cancelled'
            job.error_message = 'Остановлено оператором'
            await db.commit()
        logger.info(f"Задание {job_id} отменено")