# test_print_queue_workers.py
"""Тесты воркеров очереди печати (services/print_queue.py).

Очередь создаёт отдельный воркер на каждый принтер автоматически при
постановке задания (без перезапуска сервиса и без PRINTER_WORKERS):
  * задания на разные принтеры печатаются параллельно;
  * задания на один принтер — строго последовательно.

Тесты не требуют БД/принтера: ``_process_task``/``_get_db``/``_close_db``
подменяются.
"""

import asyncio
from uuid import uuid4

from services.print_queue import PrinterQueue, PrintTask


def _make_task(ip: str, port: int = 9100):
    return PrintTask(
        job_id=uuid4(),
        zpl_code='^XA^XZ',
        printer_ip=ip,
        printer_port=port,
        marking_date='2026-01-01',
        expiration_date='2026-02-01',
        batch_number='1',
        first_box=1,
        boxes_count=1,
    )


def _patch(queue: PrinterQueue, process):
    queue._process_task = process

    async def _get_db():
        return None, None

    async def _close_db(db, gen):
        return None

    queue._get_db = _get_db
    queue._close_db = _close_db


def test_different_printers_run_in_parallel():
    """Задания на разные принтеры стартуют одновременно (разные воркеры)."""
    async def scenario():
        queue = PrinterQueue(db_getter=lambda: None)
        queue._running = True

        started = []

        async def process(task, db):
            started.append(task.printer_ip)
            await asyncio.sleep(0.2)

        _patch(queue, process)
        await queue.enqueue(_make_task('10.0.0.1'))
        await queue.enqueue(_make_task('10.0.0.2'))

        await asyncio.sleep(0.05)
        assert set(started) == {'10.0.0.1', '10.0.0.2'}, started
        assert len(queue._workers) == 2

        await asyncio.sleep(0.3)
        await queue.stop()

    asyncio.run(scenario())


def test_same_printer_is_sequential():
    """Задания на один принтер обрабатываются строго по одному (общий воркер)."""
    async def scenario():
        queue = PrinterQueue(db_getter=lambda: None)
        queue._running = True

        events = []
        active = 0
        max_active = 0

        async def process(task, db):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            events.append(('start', str(task.job_id)))
            await asyncio.sleep(0.1)
            events.append(('end', str(task.job_id)))
            active -= 1

        _patch(queue, process)
        t1 = _make_task('10.0.0.9')
        t2 = _make_task('10.0.0.9')
        await queue.enqueue(t1)
        await queue.enqueue(t2)

        await asyncio.sleep(0.35)
        assert max_active == 1, f'одновременно выполнялось {max_active} заданий'
        assert events == [
            ('start', str(t1.job_id)), ('end', str(t1.job_id)),
            ('start', str(t2.job_id)), ('end', str(t2.job_id)),
        ]
        assert len(queue._workers) == 1

        await queue.stop()

    asyncio.run(scenario())


def test_worker_created_lazily_per_printer():
    """Воркеров ровно столько, сколько принтеров получили задания."""
    async def scenario():
        queue = PrinterQueue(db_getter=lambda: None)
        queue._running = True

        async def process(task, db):
            return None

        _patch(queue, process)
        assert queue._workers == {}

        await queue.enqueue(_make_task('10.0.0.1'))
        await queue.enqueue(_make_task('10.0.0.1'))  # тот же принтер
        await queue.enqueue(_make_task('10.0.0.2'))
        assert set(queue._workers) == {'10.0.0.1:9100', '10.0.0.2:9100'}

        await asyncio.sleep(0.05)
        await queue.stop()

    asyncio.run(scenario())


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])
