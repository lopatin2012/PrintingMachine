# routers/workshop.py

from typing import List
import logging
from uuid import UUID

from fastapi import APIRouter, Form, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from crud.workshop import WorkshopCRUD
from schemas import WorkshopCreate, WorkshopUpdate, WorkshopResponse
from models import User, Workshop

# Шаблоны.
from templates_config import templates
from security import get_current_user, get_current_admin

logger = logging.getLogger(__name__)
router = APIRouter(tags=['workshops'])
workshop_crud = WorkshopCRUD()

@router.get('/workshops', response_class=HTMLResponse)
async def workshop_page(
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Страница цехов"""
    # Получаем все цеха.
    workshops = await workshop_crud.get_multi(db)

    # Получаем параметры из URL для уведомлений
    success = request.query_params.get('success')
    error = request.query_params.get('error')

    return templates.TemplateResponse(
        'workshops.html',
        {
            'request': request,
            'workshops': workshops,
            'user': current_user,
            'success': success,
            'error': error
        }
    )

@router.post('/workshops')
async def workshop_create(
        request: Request,
        name: str = Form(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Добавить цех"""
    existing = await workshop_crud.get_by_name(db, name)

    if existing:
        return templates.TemplateResponse(
            'workshops.html',
            {
                'request': request,
                'error': f'Цех с названием {name} уже существует!',
                'workshops': await workshop_crud.get_multi(db),
                'user': current_user,
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    # Создаём цех.
    workshop_data = WorkshopCreate(name=name)
    workshop = await workshop_crud.create(db, workshop_data)

    logger.info(f'Цех "{name}" создан пользователем {current_user.login}')

    return RedirectResponse(
        url='workshops?success=Цех успешно добавлен',
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post('/workshops/{workshop_id}')
async def workshop_update(
        workshop_id: UUID,
        request: Request,
        name: str = Form(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Редактор цех"""
    # Проверка наличия цеха с указанным UUID
    is_has_workshop = await workshop_crud.get(db, workshop_id)
    if not is_has_workshop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Цех не найден'
        )

    # Проверка уникальности наименования цеха.
    is_has_name_workshop = await workshop_crud.get_by_name(db, name)
    if is_has_name_workshop:
        return templates.TemplateResponse(
            'workshops.html',
            {
                'request': request,
                'error': f'Цех с наименованием {name} уже существует',
                'workshops': await workshop_crud.get_multi(db),
                'user': current_user
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    workshop_data = WorkshopUpdate(name=name)
    updated = await workshop_crud.update(db, workshop_id, workshop_data)

    logger.info(
        f'Цех {workshop_id} был обновлён пользователем {current_user.login}.'
        f' Изменилось наименование на {name}'
    )

    return RedirectResponse(
        url='/workshops',
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post('/workshops/{workshop_id}/delete')
async def workshop_delete(
        workshop_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Удалить цех"""
    # Проверяем существование цеха.
    workshop = await workshop_crud.get(db, workshop_id)
    if not workshop:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f'Цех с id {workshop_id} не найден'
        )

    # Удаление (каскадом)
    success = await workshop_crud.delete(db, workshop_id)

    if success:
        logger.info(f'Цех {workshop.name} удалён пользователем {current_user.login}')
        return RedirectResponse(
            url='/workshops?success=Цех успешно удалён',
            status_code=status.HTTP_303_SEE_OTHER
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Ошибка при удалении цеха'
        )
