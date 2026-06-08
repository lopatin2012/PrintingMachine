# routers/printer.py

import os
import subprocess
import ipaddress
import logging
import platform
from uuid import UUID
import socket

from fastapi import APIRouter, Form, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from crud.line import LineCRUD
from database import get_db
from crud.printer import PrinterCRUD
from schemas import PrinterCreate, PrinterUpdate, PrinterResponse
from models import User, Line, Printer, Workshop

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
            'error': error
        }
    )

@router.post('/printers')
async def printer_create(
        request: Request,
        name: str = Form(...),
        line_id: UUID = Form(...),
        ip_address: str = Form(...),
        port_address: int = Form(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Добавить принтер"""
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
        port_address=port_address
    )
    added = await printer_crud.create(db, printer_data)

    logger.info(
        f'Принтер "{name}" ({ip_address}:{port_address}) добавлен на линию "{line.name}" '
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
        port_address=port_address
    )
    updated = await printer_crud.update(db, printer_id, printer_data)

    logger.info(
        f'Принтер {printer_id} обновлён пользователем {current_user.login}. '
        f'Новое название: {name}, IP: {ip_address}:{port_address}, линия: {line.name}'
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

@router.post('/printers/{printer_id}/test')
async def test_printer_connection(
        printer_id: UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Проверка доступности принтера"""
    printer = await printer_crud.get(db, printer_id)
    if not printer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Принтер не найден'
        )

    try:
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        command = ['ping', param, '1', printer.ip_address]

        output = subprocess.run(command, capture_output=True, text=True, timeout=1)
        is_available = output.returncode == 0
        message = f'В сети'
        logger.info(f'Принтер {printer.name} доступен')
    except (socket.timeout, socket.error, OSError) as e:
        is_available = False
        message = f' Ошибка: {str(e)}'
        logger.error(f'Ошибка подключения к принтеру {printer.name}: {e}')

    return {
        'status': 'success' if is_available else 'error',
        'available': is_available,
        'message': message,
        'printer': {
            'id': str(printer.id),
            'name': printer.name,
            'ip': printer.ip_address,
            'port': printer.port_address
        }
    }
