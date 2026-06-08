# routers/line.py

import logging
from uuid import UUID

from fastapi import APIRouter, Form, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from crud.line import LineCRUD
from crud.workshop import WorkshopCRUD
from schemas import LineCreate, LineUpdate
from models import User, Line, Workshop

from templates_config import templates
from security import get_current_user, get_current_admin

logging = logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=['lines'])
line_crud = LineCRUD()
workshop_crud = WorkshopCRUD()

@router.get('/lines', response_class=HTMLResponse)
async def line_page(
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Страница линий"""
    # Получаем все линии с цеха.
    result = await db.execute(
        select(Line)
        .join(Workshop, Line.workshop_id == Workshop.id)
        .order_by(Workshop.name, Line.name)
    )
    lines = result.scalars().all()

    # Получаем все цеха для фильтра и выпадающего списка.
    workshops = await workshop_crud.get_multi(db)

    # Параметры уведомлений.
    success = request.query_params.get('success')
    error = request.query_params.get('error')

    return templates.TemplateResponse(
        'lines.html',
        {
            'request': request,
            'lines': lines,
            'workshops': workshops,
            'user': current_user,
            'success': success,
            'error': error
        }
    )

@router.post('/lines')
async def line_create(
        request: Request,
        name: str = Form(...),
        workshop_id: UUID = Form(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Добавить линию"""
    # Валидация.
    name = name.strip()
    if len(name) < 2:
        return RedirectResponse(
            url='/lines?error=Название линии должно содержать минимум 2 символа',
            status_code=status.HTTP_303_SEE_OTHER
        )
    if len(name) > 50:
        return RedirectResponse(
            url='/lines?error=Название линии не должно превышать 50 символов',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка существования цеха.
    workshop = await workshop_crud.get(db, workshop_id)
    if not workshop:
        return RedirectResponse(
            url='/lines?error=Выбранный цех не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка уникальности названия линии (глобально)
    existing = await line_crud.get_by_name(db, name)
    if existing:
        return RedirectResponse(
            url=f'/lines?error=Линия с названием "{name}" уже существует',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Создать линию.
    line_data = LineCreate(name=name, workshop_id=workshop_id)
    line = await line_crud.create(db, line_data)

    return RedirectResponse(
        url=f'/lines?success=Линия "{name}" успешно добавлена',
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post('/lines/{line_id}')
async def line_update(
        line_id: UUID,
        request: Request,
        name: str = Form(...),
        workshop_id: UUID = Form(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Редактирование линии"""
    # Проверка её существования.
    line = await line_crud.get(db, line_id)
    if not line:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Линия не найдена'
        )

    # Валидация
    name = name.strip()
    if len(name) < 2:
        return RedirectResponse(
            url='/lines?error=Название линии должно содержать минимум 2 символа',
            status_code=status.HTTP_303_SEE_OTHER
        )

    if len(name) > 50:
        return RedirectResponse(
            url='/lines?error=Название линии не должно превышать 50 символов',
            status_code=status.HTTP_303_SEE_OTHER
        )

    workshop = await workshop_crud.get(db, workshop_id)
    if not workshop:
        return RedirectResponse(
            url='/lines?error=Выбранный цех не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка уникальности
    existing = await line_crud.get_by_name(db, name)
    if existing:
        return RedirectResponse(
            url=f'/lines?error=Линия с названием "{name}" уже существует',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Обновление
    line_data = LineUpdate(name=name, workshop_id=workshop_id)
    updated = await line_crud.update(db, line_id, line_data)

    logger.info(
        f'Линия {line_id} была обновлена пользователем {current_user}. '
        f'Новое название: {name}, цех: {workshop.name}'
    )

    return RedirectResponse(
        url=f'/lines?success=Линия {name} успешно обновлена',
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post('/lines/{line_id}/delete')
async def line_delete(
        line_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Удалить линию"""
    # Проверка существования
    line = await line_crud.get(db, line_id)
    if not line:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Линия с id {line_id} не найдена'
        )

    # Логирование
    workshop = await workshop_crud.get(db, line.workshop_id)
    workshop_name = workshop.name if workshop else 'Неизвестный цех'

    # Удаление. Каскадом
    success = await line_crud.delete(db, line_id)

    if success:
        logger.info(
            f'Линия {line.name} из цеха {workshop_name} '
            f'удалена пользователем {current_user.login}'
        )
        return RedirectResponse(
            url=f'/lines?success=Линия {line.name} успешно удалена',
            status_code=status.HTTP_303_SEE_OTHER
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Ошибка при удалении линии'
        )
