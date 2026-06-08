# routers/workshop_user.py

import logging
from uuid import UUID
from typing import  Optional

from fastapi import APIRouter, Form, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from crud.workshop_user import WorkshopUserCRUD
from crud.user import UserCRUD
from crud.workshop import WorkshopCRUD
from crud.line import LineCRUD
from schemas import WorkshopUserCreate, WorkshopUserUpdate
from models import User, WorkshopUser, Workshop, Line

from templates_config import templates
from security import get_current_user, get_current_admin

logger = logging.getLogger(__name__)
router = APIRouter(tags=['workshop_users'])
workshop_user_crud = WorkshopUserCRUD()
user_crud = UserCRUD()
workshop_crud = WorkshopCRUD()
line_crud = LineCRUD()


@router.get('/workshop-users', response_class=HTMLResponse)
async def workshop_user_page(
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Страница управления доступом пользователей к цехам"""
    # Получаем все привязки с пользователями, цехами и линиями
    result = await db.execute(
        select(WorkshopUser)
        .join(User, WorkshopUser.user_id == User.id)
        .join(Workshop, WorkshopUser.workshop_id == Workshop.id)
        .join(Line, WorkshopUser.line_id == Line.id, isouter=True)
        .order_by(User.login, Workshop.name, Line.name)
    )
    workshop_users = result.scalars().all()

    # Получаем всех пользователей для фильтра и выпадающего списка
    users_result = await db.execute(
        select(User)
        .join(User.role)
        .order_by(User.login)
    )
    users = users_result.scalars().all()

    # Получаем все цеха с линиями для фильтра и выпадающего списка
    workshops_result = await db.execute(
        select(Workshop)
        .order_by(Workshop.name)
    )
    workshops = workshops_result.scalars().all()

    # Параметры уведомлений
    success = request.query_params.get('success')
    error = request.query_params.get('error')

    return templates.TemplateResponse(
        'workshop_users.html',
        {
            'request': request,
            'workshop_users': workshop_users,
            'users': users,
            'workshops': workshops,
            'user': current_user,
            'success': success,
            'error': error
        }
    )


@router.post('/workshop-users')
async def workshop_user_create(
        request: Request,
        user_id: UUID = Form(...),
        workshop_id: UUID = Form(...),
        line_id: Optional[UUID] = Form(None),
        role_in_workshop: str = Form(...),
        comment: Optional[str] = Form(None),
        is_active: bool = Form(True),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Добавить доступ пользователя к цеху"""
    # Валидация роли в цеху
    allowed_roles = ['master', 'operator', 'supervisor']
    if role_in_workshop not in allowed_roles:
        return RedirectResponse(
            url=f'/workshop-users?error=Недопустимая роль в цеху: {role_in_workshop}',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка существования пользователя
    user = await user_crud.get(db, user_id)
    if not user:
        return RedirectResponse(
            url='/workshop-users?error=Выбранный пользователь не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка существования цеха
    workshop = await workshop_crud.get(db, workshop_id)
    if not workshop:
        return RedirectResponse(
            url='/workshop-users?error=Выбранный цех не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка существования линии (если указана)
    if line_id:
        line = await line_crud.get(db, line_id)
        if not line:
            return RedirectResponse(
                url='/workshop-users?error=Выбранная линия не найдена',
                status_code=status.HTTP_303_SEE_OTHER
            )
        # Проверка, что линия принадлежит цеху
        if line.workshop_id != workshop_id:
            return RedirectResponse(
                url='/workshop-users?error=Линия не принадлежит выбранному цеху',
                status_code=status.HTTP_303_SEE_OTHER
            )

    # Проверка уникальности (пользователь + цех)
    result = await db.execute(
        select(WorkshopUser).where(
            WorkshopUser.user_id == user_id,
            WorkshopUser.workshop_id == workshop_id
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return RedirectResponse(
            url=f'/workshop-users?error=Пользователь "{user.login}" уже имеет доступ к цеху "{workshop.name}"',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Создание привязки
    workshop_user_data = WorkshopUserCreate(
        user_id=user_id,
        workshop_id=workshop_id,
        line_id=line_id,
        role_in_workshop=role_in_workshop,
        comment=comment.strip() if comment else None,
        is_active=is_active
    )
    workshop_user = await workshop_user_crud.create(db, workshop_user_data)

    logger.info(
        f'Добавлен доступ: пользователь "{user.login}" → цех "{workshop.name}" '
        f'(роль: {role_in_workshop}, линия: {line.name if line_id and line else "все"}) '
        f'пользователем {current_user.login}'
    )

    return RedirectResponse(
        url='/workshop-users?success=Доступ успешно добавлен',
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post('/workshop-users/{workshop_user_id}')
async def workshop_user_update(
        workshop_user_id: UUID,
        request: Request,
        user_id: UUID = Form(...),
        workshop_id: UUID = Form(...),
        line_id: Optional[UUID] = Form(None),
        role_in_workshop: str = Form(...),
        comment: Optional[str] = Form(None),
        is_active: bool = Form(True),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Редактировать доступ пользователя к цеху"""
    # Проверка существования
    workshop_user = await workshop_user_crud.get(db, workshop_user_id)
    if not workshop_user:
        return RedirectResponse(
            url='/workshop-users?error=Привязка не найдена',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Валидация роли в цеху
    allowed_roles = ['master', 'operator', 'supervisor']
    if role_in_workshop not in allowed_roles:
        return RedirectResponse(
            url=f'/workshop-users?error=Недопустимая роль в цеху: {role_in_workshop}',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка существования пользователя
    user = await user_crud.get(db, user_id)
    if not user:
        return RedirectResponse(
            url='/workshop-users?error=Выбранный пользователь не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка существования цеха
    workshop = await workshop_crud.get(db, workshop_id)
    if not workshop:
        return RedirectResponse(
            url='/workshop-users?error=Выбранный цех не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка существования линии (если указана)
    if line_id:
        line = await line_crud.get(db, line_id)
        if not line:
            return RedirectResponse(
                url='/workshop-users?error=Выбранная линия не найдена',
                status_code=status.HTTP_303_SEE_OTHER
            )
        # Проверка, что линия принадлежит цеху
        if line.workshop_id != workshop_id:
            return RedirectResponse(
                url='/workshop-users?error=Линия не принадлежит выбранному цеху',
                status_code=status.HTTP_303_SEE_OTHER
            )

    # Проверка уникальности (исключая текущую запись)
    result = await db.execute(
        select(WorkshopUser).where(
            WorkshopUser.user_id == user_id,
            WorkshopUser.workshop_id == workshop_id,
            WorkshopUser.id != workshop_user_id
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return RedirectResponse(
            url=f'/workshop-users?error=Пользователь "{user.login}" уже имеет доступ к цеху "{workshop.name}"',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Обновление привязки
    workshop_user_data = WorkshopUserUpdate(
        user_id=user_id,
        workshop_id=workshop_id,
        line_id=line_id,
        role_in_workshop=role_in_workshop,
        comment=comment.strip() if comment else None,
        is_active=is_active
    )
    updated = await workshop_user_crud.update(db, workshop_user_id, workshop_user_data)

    logger.info(
        f'Обновлён доступ: пользователь "{user.login}" → цех "{workshop.name}" '
        f'(ID: {workshop_user_id}) пользователем {current_user.login}'
    )

    return RedirectResponse(
        url='/workshop-users?success=Доступ успешно обновлён',
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post('/workshop-users/{workshop_user_id}/activate')
async def workshop_user_activate(
        workshop_user_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Активировать доступ"""
    workshop_user = await workshop_user_crud.get(db, workshop_user_id)
    if not workshop_user:
        return RedirectResponse(
            url='/workshop-users?error=Привязка не найдена',
            status_code=status.HTTP_303_SEE_OTHER
        )

    workshop_user_data = WorkshopUserUpdate(is_active=True)
    updated = await workshop_user_crud.update(db, workshop_user_id, workshop_user_data)

    logger.info(
        f'Активирован доступ пользователя "{workshop_user.user.login}" '
        f'к цеху "{workshop_user.workshop.name}" (ID: {workshop_user_id}) '
        f'пользователем {current_user.login}'
    )

    return RedirectResponse(
        url='/workshop-users?success=Доступ активирован',
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post('/workshop-users/{workshop_user_id}/deactivate')
async def workshop_user_deactivate(
        workshop_user_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Деактивировать доступ"""
    workshop_user = await workshop_user_crud.get(db, workshop_user_id)
    if not workshop_user:
        return RedirectResponse(
            url='/workshop-users?error=Привязка не найдена',
            status_code=status.HTTP_303_SEE_OTHER
        )

    workshop_user_data = WorkshopUserUpdate(is_active=False)
    updated = await workshop_user_crud.update(db, workshop_user_id, workshop_user_data)

    logger.info(
        f'Деактивирован доступ пользователя "{workshop_user.user.login}" '
        f'к цеху "{workshop_user.workshop.name}" (ID: {workshop_user_id}) '
        f'пользователем {current_user.login}'
    )

    return RedirectResponse(
        url='/workshop-users?success=Доступ деактивирован',
        status_code=status.HTTP_303_SEE_OTHER
    )


@router.post('/workshop-users/{workshop_user_id}/delete')
async def workshop_user_delete(
        workshop_user_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Удалить привязку"""
    workshop_user = await workshop_user_crud.get(db, workshop_user_id)
    if not workshop_user:
        return RedirectResponse(
            url='/workshop-users?error=Привязка не найдена',
            status_code=status.HTTP_303_SEE_OTHER
        )

    success = await workshop_user_crud.delete(db, workshop_user_id)

    if success:
        logger.info(
            f'Удалён доступ пользователя "{workshop_user.user.login}" '
            f'к цеху "{workshop_user.workshop.name}" (ID: {workshop_user_id}) '
            f'пользователем {current_user.login}'
        )
        return RedirectResponse(
            url='/workshop-users?success=Доступ успешно удалён',
            status_code=status.HTTP_303_SEE_OTHER
        )
    else:
        return RedirectResponse(
            url='/workshop-users?error=Ошибка при удалении доступа',
            status_code=status.HTTP_303_SEE_OTHER
        )
