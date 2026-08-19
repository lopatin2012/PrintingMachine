# routers/printer.py

import asyncio
import ipaddress
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Body, Form, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from crud.line import LineCRUD
from database import get_db
from crud.printer import PrinterCRUD
from schemas import PrinterCreate, PrinterUpdate
from models import User, Line, Printer, Workshop, PrintJob
from helpers.printer_drivers import get_driver_or_default, get_printer_driver, printer_types
from helpers.printers import (
    check_printer_status_async,
    clear_printer_queue_async,
    restart_printer_async,
)

# Шаблоны.
from templates_config import templates
from security import get_current_user, get_current_admin


logger = logging.getLogger(__name__)
router = APIRouter(tags=['printers'])
printer_crud = PrinterCRUD()
line_crud = LineCRUD()

@router.get('/printers', response_class=HTMLResponse)
async def printer_page(
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Страница принтеров"""
    result = await db.execute(
        select(Printer)
        .join(Line, Printer.line_id == Line.id)
        .join(Workshop, Line.workshop_id == Workshop.id)
        .order_by(Workshop.name, Line.name, Printer.name)
    )

    printers = result.scalars().all()

    # Получение цехов по фильтру
    workshops_result = await db.execute(
        select(Workshop)
        .order_by(Workshop.name)
    )
    workshops = workshops_result.scalars().all()

    # Получение всех линий.
    lines_result = await db.execute(
        select(Line)
        .join(Workshop, Line.workshop_id == Workshop.id)
        .order_by(Workshop.name, Line.name)
    )
    lines = lines_result.scalars().all()

    # Параметры уведомлений.
    success = request.query_params.get('success')
    error = request.query_params.get('error')

    return templates.TemplateResponse(
        'printers.html',
        {
            'request': request,
            'printers': printers,
            'workshops': workshops,
            'lines': lines,
            'user': current_user,
            'success': success,
            'error': error,
            'printer_types': printer_types(),
        }
    )

@router.post('/printers')
async def printer_create(
        request: Request,
        name: str = Form(...),
        line_id: UUID = Form(...),
        ip_address: str = Form(...),
        port_address: int = Form(...),
        printer_type: str = Form('zebra'),
        buffer_limit: int = Form(25),
        batch_size: int = Form(5),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Добавить принтер"""
    name = name.strip()
    printer_type = printer_type.strip().lower()

    if buffer_limit < 1 or buffer_limit > 5000:
        return RedirectResponse(
            url='/printers?error=Буфер очереди должен быть от 1 до 5000 этикеток',
            status_code=status.HTTP_303_SEE_OTHER
        )
    if batch_size < 1 or batch_size > 500:
        return RedirectResponse(
            url='/printers?error=Размер пачки должен быть от 1 до 500 этикеток',
            status_code=status.HTTP_303_SEE_OTHER
        )

    if get_printer_driver(printer_type) is None:
        supported = ', '.join(t['key'] for t in printer_types())
        return RedirectResponse(
            url=f'/printers?error=Тип принтера должен быть одним из: {supported}',
            status_code=status.HTTP_303_SEE_OTHER
        )

    if len(name) < 2:
        return RedirectResponse(
            url='/printers?error=Название принтера должно содержать минимум 2 символа',
            status_code=status.HTTP_303_SEE_OTHER
        )

    if len(name) > 50:
        return RedirectResponse(
            url='/printers?error=Название принтера не должно превышать 50 символов',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Валидируем данные.
    try:
        ipaddress.ip_address(ip_address)
    except ValueError:
        return RedirectResponse(
            url=f'/printers?error=Некорректный IP-адрес: {ip_address}',
            status_code=status.HTTP_303_SEE_OTHER
        )

    if port_address < 1 or port_address > 65535:
        return RedirectResponse(
            url=f'/printers?error=Некорректный порт: {port_address}',
            status_code=status.HTTP_303_SEE_OTHER

        )

    line = await line_crud.get(db, line_id)
    if not line:
        return RedirectResponse(
            url='/printers?error=Выбранная линия не найдена',
            status_code=status.HTTP_303_SEE_OTHER
        )

    existing_by_name = await printer_crud.get_by_name(db, name)
    if existing_by_name:
        return RedirectResponse(
            url=f'/printers?error=Принтер с названием {name} уже существует'
        )

    existing_by_ip = await printer_crud.get_by_ip(db, ip_address)
    if existing_by_ip:
        return RedirectResponse(
            url=f'/printers?error=Принтер с IP-адресом "{ip_address}" уже существует',
            status_code=status.HTTP_303_SEE_OTHER
        )

    printer_data = PrinterCreate(
        name=name,
        line_id=line_id,
        ip_address=ip_address,
        port_address=port_address,
        printer_type=printer_type,
        buffer_limit=buffer_limit,
        batch_size=batch_size,
    )
    added = await printer_crud.create(db, printer_data)

    logger.info(
        f'Принтер "{name}" ({ip_address}:{port_address}, тип: {printer_type}) добавлен на линию "{line.name}" '
        f'(цех: {line.workshop.name if line.workshop else "не указан"}) '
        f'пользователем {current_user.login}'
    )

    return RedirectResponse(
        url='/printers?success=Принтер успешно добавлен',
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post('/printers/{printer_id}')
async def printer_update(
    printer_id: UUID,
    request: Request,
    name: str = Form(...),
    line_id: UUID = Form(...),
    ip_address: str = Form(...),
    port_address: int = Form(9100),
    printer_type: str = Form('zebra'),
    buffer_limit: int = Form(25),
    batch_size: int = Form(5),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """Редактирование записи о принтере"""
    printer = await printer_crud.get(db, printer_id)
    if not printer:
        return RedirectResponse(
            url='/printers?error=Принтер не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    if buffer_limit < 1 or buffer_limit > 5000:
        return RedirectResponse(
            url='/printers?error=Буфер очереди должен быть от 1 до 5000 этикеток',
            status_code=status.HTTP_303_SEE_OTHER
        )
    if batch_size < 1 or batch_size > 500:
        return RedirectResponse(
            url='/printers?error=Размер пачки должен быть от 1 до 500 этикеток',
            status_code=status.HTTP_303_SEE_OTHER
        )

    printer_type = printer_type.strip().lower()
    if get_printer_driver(printer_type) is None:
        supported = ', '.join(t['key'] for t in printer_types())
        return RedirectResponse(
            url=f'/printers?error=Тип принтера должен быть одним из: {supported}',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Валидация названия
    name = name.strip()
    if len(name) < 2:
        return RedirectResponse(
            url='/printers?error=Название принтера должно содержать минимум 2 символа',
            status_code=status.HTTP_303_SEE_OTHER
        )
    if len(name) > 50:
        return RedirectResponse(
            url='/printers?error=Название принтера не должно превышать 50 символов',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Валидация IP-адреса
    try:
        ipaddress.ip_address(ip_address)
    except ValueError:
        return RedirectResponse(
            url=f'/printers?error=Некорректный IP-адрес: {ip_address}',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Валидация порта
    if port_address < 1 or port_address > 65535:
        return RedirectResponse(
            url=f'/printers?error=Порт должен быть в диапазоне от 1 до 65535',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка существования линии
    line = await line_crud.get(db, line_id)
    if not line:
        return RedirectResponse(
            url='/printers?error=Выбранная линия не найдена',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка уникальности названия
    existing_by_name = await printer_crud.get_by_name(db, name)
    if existing_by_name and existing_by_name.id != printer_id:
        return RedirectResponse(
            url=f'/printers?error=Принтер с названием "{name}" уже существует на линии "{existing_by_name.line.name if existing_by_name.line else "неизвестной"}"',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка уникальности IP-адреса
    existing_by_ip = await printer_crud.get_by_ip(db, ip_address)
    if existing_by_ip and existing_by_ip.id != printer_id:
        return RedirectResponse(
            url=f'/printers?error=Принтер с IP-адресом "{ip_address}" уже существует на линии "{existing_by_ip.line.name if existing_by_ip.line else "неизвестной"}"',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Обновление принтера
    printer_data = PrinterUpdate(
        name=name,
        line_id=line_id,
        ip_address=ip_address,
        port_address=port_address,
        printer_type=printer_type,
        buffer_limit=buffer_limit,
        batch_size=batch_size,
    )
    updated = await printer_crud.update(db, printer_id, printer_data)

    logger.info(
        f'Принтер {printer_id} обновлён пользователем {current_user.login}. '
        f'Новое название: {name}, IP: {ip_address}:{port_address}, тип: {printer_type}, линия: {line.name}'
    )

    return RedirectResponse(
        url='/printers?success=Принтер успешно обновлён',
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post('/printers/{printer_id}/delete')
async def printer_delete(
        printer_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Удалить принтер"""
    # Проверка существования
    printer = await printer_crud.get(db, printer_id)
    if not printer:
        return RedirectResponse(
            url=f'/printers?error=Не найден принтер с id {printer_id}',
            status_code=status.HTTP_303_SEE_OTHER,
        )

    line = await line_crud.get(db, printer.line_id)
    line_name = line.name if line else 'Неизвестная линия'

    # Удаление.
    success = await printer_crud.delete(db, printer_id)

    if success:
        logger.info(
            f'Принтер "{printer.name}" ({printer.ip_address}:{printer.port_address}) '
            f'на линии "{line_name}" (id={printer_id}) удалён пользователем {current_user.login}'
        )
        return RedirectResponse(
            url='/printers?success=Принтер успешно удалён',
            status_code=status.HTTP_303_SEE_OTHER
        )
    else:
        return RedirectResponse(
            url='/printers?error=Ошибка при удалении принтера',
            status_code=status.HTTP_303_SEE_OTHER
        )


# ─── Управление принтерами: статус, очередь, команды ─────────────────────────

def _printer_status_summary(status: dict) -> dict:
    """Нормализация статуса для фронтенда."""
    if not status.get('ok'):
        return {
            'state': 'offline',
            'label': 'Недоступен',
            'detail': status.get('error') or status.get('message') or '',
            'raw': status.get('raw', ''),
        }
    if status.get('error_flag'):
        return {
            'state': 'error',
            'label': 'Ошибка',
            'detail': status.get('message') or '; '.join(status.get('errors', [])),
            'raw': status.get('raw', ''),
        }
    if status.get('printing'):
        return {
            'state': 'printing',
            'label': 'Печать',
            'detail': status.get('message') or 'Идёт печать',
            'raw': status.get('raw', ''),
        }
    if status.get('paused'):
        return {
            'state': 'paused',
            'label': 'Пауза',
            'detail': status.get('message') or 'Принтер на паузе',
            'raw': status.get('raw', ''),
        }
    return {
        'state': 'online',
        'label': 'Готов',
        'detail': status.get('message') or 'Готов к печати',
        'raw': status.get('raw', ''),
    }


# ─── Статус принтеров: кэш + неблокирующая проверка ────────────────────────
# Проверка статуса — сетевой вызов с таймаутом. Чтобы она не «вешала» веб
# (event loop) и не дёргала принтер слишком часто, результаты кэшируются,
# а сами вызовы выполняются в отдельном потоке.
#
# Недоступные принтеры (например, устаревшие модели, которые не отвечают
# вообще) кэшируются надолго: реальная проверка не чаще раза в минуту,
# остальное время отдаётся «Недоступен» из кэша — без таймаутов и лишних
# предупреждений при каждом обновлении страницы.
_STATUS_CACHE: dict[str, tuple[float, dict]] = {}
_STATUS_CACHE_TTL = 3.0        # секунд — свежий (успешный) статус
_STATUS_CACHE_FAIL_TTL = 60.0  # секунд — ошибка/недоступность


def _status_cache_ttl(status: dict) -> float:
    return _STATUS_CACHE_FAIL_TTL if not status.get('ok') else _STATUS_CACHE_TTL


async def _get_printer_status(ip: str, port: int, printer_type: str,
                              timeout: float = 1.5) -> dict:
    """Проверка статуса с кэшем; не блокирует event loop."""
    key = f'{ip}:{port}:{printer_type or "zebra"}'
    now = time.monotonic()
    cached = _STATUS_CACHE.get(key)
    if cached and now - cached[0] < _status_cache_ttl(cached[1]):
        return cached[1]

    try:
        status = await asyncio.wait_for(
            check_printer_status_async(ip, port, printer_type, timeout=timeout),
            timeout=timeout + 0.5,
        )
    except Exception as e:
        status = {'ok': False, 'error': str(e)}

    _STATUS_CACHE[key] = (time.monotonic(), status)
    return status


def _get_cached_printer_statuses(printers) -> dict[str, dict]:
    """Статусы для первичного рендера страницы — ТОЛЬКО из кэша, без сети.

    Загрузка страницы не ждёт таймауты принтеров. Живые статусы подтягивает
    сам браузер через /api/printers/{id}/status (refreshAllStatus в шаблоне).
    """
    statuses = {}
    for p in printers:
        cached = _STATUS_CACHE.get(
            f'{p.ip_address}:{p.port_address}:{p.printer_type or "zebra"}'
        )
        if cached:
            statuses[str(p.id)] = _printer_status_summary(cached[1])
        else:
            statuses[str(p.id)] = {
                'state': 'offline',
                'label': 'Проверка...',
                'detail': 'Статус будет обновлён автоматически',
                'raw': '',
            }
    return statuses


@router.get('/printers/control', response_class=HTMLResponse)
async def printer_control_page(
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Страница управления принтерами: статус, задания, команды."""
    result = await db.execute(
        select(Printer)
        .join(Line, Printer.line_id == Line.id)
        .join(Workshop, Line.workshop_id == Workshop.id)
        .order_by(Workshop.name, Line.name, Printer.name)
    )
    printers = result.scalars().all()

    # Активные задания по принтерам.
    printer_ids = [p.id for p in printers]
    active_jobs = []
    if printer_ids:
        active_jobs = (await db.execute(
            select(PrintJob)
            .where(
                PrintJob.printer_id.in_(printer_ids),
                PrintJob.status.in_(['pending', 'processing'])
            )
            .order_by(PrintJob.created_at.desc())
        )).scalars().all()
    jobs_by_printer: dict[str, list] = {}
    for job in active_jobs:
        jobs_by_printer.setdefault(str(job.printer_id), []).append(job)

    # Первичные статусы — только из кэша (страница открывается мгновенно,
    # без ожидания сети; живой статус подтянет refreshAllStatus в браузере).
    printers_status = _get_cached_printer_statuses(printers)

    # Диапазоны параметров печати для формы управления (из драйвера типа).
    printer_params = {}
    for p in printers:
        driver = get_driver_or_default(p.printer_type)
        printer_params[str(p.id)] = {
            'contrast_min': driver.contrast_min,
            'contrast_max': driver.contrast_max,
            'speed_min': driver.speed_min,
            'speed_max': driver.speed_max,
        }

    return templates.TemplateResponse(
        'printers_control.html',
        {
            'request': request,
            'printers': printers,
            'printers_status': printers_status,
            'jobs_by_printer': jobs_by_printer,
            'printer_params': printer_params,
            'user': current_user,
        }
    )


@router.post('/api/printers/{printer_id}/status')
async def api_printer_status(
        printer_id: UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Проверка текущего статуса принтера (Zebra ~HS / TSC <ESC>!?)."""
    printer = await printer_crud.get(db, printer_id)
    if not printer:
        raise HTTPException(status_code=404, detail='Принтер не найден')

    status = await _get_printer_status(
        printer.ip_address, printer.port_address, printer.printer_type,
        timeout=3.0,
    )
    return {
        'printer_id': str(printer.id),
        'status': _printer_status_summary(status),
        'raw': status,
    }


@router.post('/api/printers/{printer_id}/clear-queue')
async def api_printer_clear_queue(
        printer_id: UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Очистка очереди печати принтера (Zebra ~JA / TSC CLS)."""
    printer = await printer_crud.get(db, printer_id)
    if not printer:
        raise HTTPException(status_code=404, detail='Принтер не найден')

    result = await clear_printer_queue_async(
        printer.ip_address, printer.port_address, printer.printer_type
    )
    if not result.get('success'):
        raise HTTPException(status_code=502, detail=f'Не удалось очистить очередь: {result.get("error", "неизвестная ошибка")}')

    logger.info(
        f'Очередь печати принтера "{printer.name}" очищена '
        f'(тип: {printer.printer_type}) пользователем {current_user.login}'
    )
    return {'success': True, 'printer_id': str(printer.id), 'message': 'Очередь печати очищена'}


@router.post('/api/printers/{printer_id}/restart')
async def api_printer_restart(
        printer_id: UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Перезапуск принтера (Zebra ~JR / TSC <ESC>!C)."""
    printer = await printer_crud.get(db, printer_id)
    if not printer:
        raise HTTPException(status_code=404, detail='Принтер не найден')

    result = await restart_printer_async(
        printer.ip_address, printer.port_address, printer.printer_type
    )
    if not result.get('success'):
        raise HTTPException(status_code=502, detail=f'Не удалось перезапустить принтер: {result.get("error", "неизвестная ошибка")}')

    logger.info(
        f'Принтер "{printer.name}" перезапущен '
        f'(тип: {printer.printer_type}) пользователем {current_user.login}'
    )
    return {'success': True, 'printer_id': str(printer.id), 'message': 'Команда перезапуска отправлена'}


# ─── Управление параметрами печати: контраст, скорость, пауза ────────────────
# Команды зависят от типа принтера и выполняются драйвером
# (helpers/printer_drivers.py) в отдельном потоке — без блокировки event loop.

def _run_printer_command(printer, method: str, *args):
    """Выполнить команду драйвера в отдельном потоке."""
    driver = get_driver_or_default(printer.printer_type)
    return asyncio.to_thread(getattr(driver, method), printer.ip_address, printer.port_address, *args)


@router.post('/api/printers/{printer_id}/contrast')
async def api_printer_set_contrast(
        printer_id: UUID,
        value: int = Body(..., ge=0, le=30, embed=True),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Установить контраст (плотность) печати."""
    printer = await printer_crud.get(db, printer_id)
    if not printer:
        raise HTTPException(status_code=404, detail='Принтер не найден')

    result = await _run_printer_command(printer, 'set_contrast', value)
    if not result.get('success'):
        raise HTTPException(
            status_code=400,
            detail=f'Не удалось установить контраст: {result.get("error", "неизвестная ошибка")}',
        )

    logger.info(
        f'Контраст принтера "{printer.name}" установлен: {value} '
        f'(тип: {printer.printer_type}) пользователем {current_user.login}'
    )
    return {
        'success': True,
        'printer_id': str(printer.id),
        'message': f'Контраст установлен: {value}'
    }


@router.post('/api/printers/{printer_id}/speed')
async def api_printer_set_speed(
        printer_id: UUID,
        value: int = Body(..., ge=1, le=14, embed=True),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Установить скорость печати (дюймов в секунду)."""
    printer = await printer_crud.get(db, printer_id)
    if not printer:
        raise HTTPException(status_code=404, detail='Принтер не найден')

    result = await _run_printer_command(printer, 'set_speed', value)
    if not result.get('success'):
        raise HTTPException(
            status_code=400,
            detail=f'Не удалось установить скорость: {result.get("error", "неизвестная ошибка")}',
        )

    logger.info(
        f'Скорость принтера "{printer.name}" установлена: {value} дюймов/с '
        f'(тип: {printer.printer_type}) пользователем {current_user.login}'
    )
    return {
        'success': True,
        'printer_id': str(printer.id),
        'message': f'Скорость установлена: {value} дюймов/с'
    }


@router.post('/api/printers/{printer_id}/pause')
async def api_printer_pause(
        printer_id: UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Поставить принтер на паузу."""
    printer = await printer_crud.get(db, printer_id)
    if not printer:
        raise HTTPException(status_code=404, detail='Принтер не найден')

    result = await _run_printer_command(printer, 'pause')
    if not result.get('success'):
        raise HTTPException(
            status_code=400,
            detail=f'Не удалось поставить на паузу: {result.get("error", "неизвестная ошибка")}',
        )

    logger.info(f'Принтер "{printer.name}" поставлен на паузу пользователем {current_user.login}')
    return {
        'success': True,
        'printer_id': str(printer.id),
        'message': 'Принтер поставлен на паузу'
    }


@router.post('/api/printers/{printer_id}/resume')
async def api_printer_resume(
        printer_id: UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Снять принтер с паузы."""
    printer = await printer_crud.get(db, printer_id)
    if not printer:
        raise HTTPException(status_code=404, detail='Принтер не найден')

    result = await _run_printer_command(printer, 'resume')
    if not result.get('success'):
        raise HTTPException(
            status_code=400,
            detail=f'Не удалось снять с паузы: {result.get("error", "неизвестная ошибка")}',
        )

    logger.info(f'Принтер "{printer.name}" снят с паузы пользователем {current_user.login}')
    return {
        'success': True,
        'printer_id': str(printer.id),
        'message': 'Принтер снят с паузы'
    }
