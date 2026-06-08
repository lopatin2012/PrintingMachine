# routers/role.py

import logging
from uuid import UUID
from typing import List

from fastapi import APIRouter, Form, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, func

from database import get_db
from crud.role import RoleCRUD
from schemas import RoleCreate, RoleUpdate
from models import User, Role

from templates_config import templates
from security import get_current_user, get_current_admin

logger = logging.getLogger(__name__)
router = APIRouter(tags=['roles'])
role_crud = RoleCRUD()

@router.get('/roles', response_class=HTMLResponse)
async def role_page(
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Страница ролей"""
    # Получаем все роли с сортировкой от системных к остальным.
    result = await db.execute(
        select(Role)
        .options(selectinload(Role.users))
        .order_by(
            Role.is_admin.desc(),
            Role.is_editor.desc(),
            Role.name
        )
    )
    roles = result.scalars().all()

    # Уведомления.
    success = request.query_params.get('success')
    error = request.query_params.get('error')

    return templates.TemplateResponse(
        'roles.html',
        {
            'request': request,
            'roles': roles,
            'user': current_user,
            'success': success,
            'error': error
        }
    )

@router.post('/roles')
async def role_create(
        request: Request,
        name: str = Form(...),
        description: str = Form(None),
        is_admin: bool = Form(False),
        is_editor: bool = Form(False),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Добавить роль"""
    name = name.strip()
    if len(name) < 2:
        return RedirectResponse(
            url='/roles?error=Название роли должно содержать минимум 2 символа',
            status_code=status.HTTP_303_SEE_OTHER
        )
    if len(name) > 50:
        return RedirectResponse(
            url='/roles?error=Название роли не должно превышать 50 символов',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Защита системных ролей.
    lower_name = name.lower()
    if lower_name in ['admin', 'админ', 'administrator', 'user', 'пользователь', 'editor', 'редактор']:
        return RedirectResponse(
            url='/roles?error=Нельзя создавать роль с системным названием',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка уникальности.
    result = await db.execute(
        select(Role).where(func.lower(Role.name) == func.lower(name))
    )
    existing = result.scalar_one_or_none()

    if existing:
        return RedirectResponse(
            url=f'/roles?error=Роль с названием "{name}" уже существует',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Создание роли.
    role_data = RoleCreate(
        name=name,
        description=description.strip() if description else None,
        is_admin=is_admin,
        is_editor=is_editor
    )
    role = await role_crud.create(db, role_data)

    logger.info(f'Роль "{name}" создана пользователем {current_user}')

    return RedirectResponse(
        url='/roles?success=Роль успешно',
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post('/roles/{role_id}')
async def role_update(
        role_id: UUID,
        request: Request,
        name: str = Form(...),
        description: str = Form(None),
        is_admin: bool = Form(False),
        is_editor: bool = Form(False),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Редактировать роль"""
    # Проверка существования.
    role = await role_crud.get(db, role_id)
    if not role:
        return RedirectResponse(
            url='/roles?error=Роль не найдена',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Защита системных ролей от переименовывания/
    if role.name.lower() in ['admin', 'editor', 'user'] and role.name.lower():
        return RedirectResponse(
            url='/roles?error=Нельзя изменять название системных ролей',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Валидация названия
    name = name.strip()
    if len(name) < 2:
        return RedirectResponse(
            url='/roles?error=Название роли должно содержать минимум 2 символа',
            status_code=status.HTTP_303_SEE_OTHER
        )
    if len(name) > 50:
        return RedirectResponse(
            url='/roles?error=Название роли не должно превышать 50 символов',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка уникальности (исключая текущую роль)
    result = await db.execute(
        select(Role).where(
            func.lower(Role.name) == func.lower(name),
            Role.id != role_id
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return RedirectResponse(
            url=f'/roles?error=Роль с названием "{name}" уже существует',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Обновление
    role_data = RoleUpdate(
        name=name,
        description=description.strip() if description else None,
        is_admin=is_admin,
        is_editor=is_editor
    )
    updated = await role_crud.update(db, role_id, role_data)

    logger.info(f'Роль "{role.name}" обновлена пользователем {current_user.login}')

    return RedirectResponse(
        url='/roles?success=Роль успешно обновлена',
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post('/roles/{role_id}/delete')
async def role_delete(
        role_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Удалить роль"""
    # Проверка существования
    role = await role_crud.get(db, role_id)
    if not role:
        return RedirectResponse(
            url='/roles?error=Роль не найдена',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Защита системных ролей
    if role.name.lower() in ['admin', 'user']:
        return RedirectResponse(
            url='/roles?error=Системные роли нельзя удалять',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Нельзя удалять роль, под которой сейчас авторизирован пользователь.
    if role.id == current_user.role_id:
        return RedirectResponse(
            url='/roles?error=Нельзя удалить роль, под которой вы сейчас авторизованы',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка наличия пользователей с этой ролью
    from models import User
    result = await db.execute(
        select(func.count()).select_from(User).where(User.role_id == role_id)
    )
    user_count = result.scalar_one()

    if user_count > 0:
        # Получаем роль "Пользователь" для перевода
        user_role_result = await db.execute(
            select(Role).where(func.lower(Role.name) == 'user')
        )
        user_role = user_role_result.scalar_one_or_none()

        if not user_role:
            return RedirectResponse(
                url='/roles?error=Невозможно удалить роль: роль "Пользователь" не найдена',
                status_code=status.HTTP_303_SEE_OTHER
            )

        # Переводим пользователей на роль "Пользователь"
        await db.execute(
            select(User).where(User.role_id == role_id)
        )
        users = (await db.execute(
            select(User).where(User.role_id == role_id)
        )).scalars().all()

        for user in users:
            user.role_id = user_role.id

        await db.commit()

        logger.info(
            f'Роль "{role.name}" удалена пользователем {current_user.login}. '
            f'{user_count} пользователей переведены на роль "{user_role.name}"'
        )

    # Удаление роли
    success = await role_crud.delete(db, role_id)

    if success:
        logger.info(f'Роль "{role.name}" (id={role_id}) удалена пользователем {current_user.login}')
        return RedirectResponse(
            url='/roles?success=Роль успешно удалена',
            status_code=status.HTTP_303_SEE_OTHER
        )
    else:
        return RedirectResponse(
            url='/roles?error=Ошибка при удалении роли',
            status_code=status.HTTP_303_SEE_OTHER
        )
