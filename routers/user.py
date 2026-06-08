# routers/user.py

import logging
from uuid import UUID

from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from database import get_db
from crud.role import RoleCRUD
from crud.user import UserCRUD
from schemas import UserCreate, UserUpdate
from models import User, Role

from templates_config import templates
from security import get_current_user, get_current_admin
from auth_utils import get_password_hash

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/users', tags=['users'])  # Префикс /users
user_crud = UserCRUD()
role_crud = RoleCRUD()

@router.get('/', response_class=HTMLResponse)
async def user_page(
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Страница пользователей"""
    # Получаем всех пользователей с ролями через JOIN
    result = await db.execute(
        select(User)
        .join(Role, User.role_id == Role.id)
        .order_by(
            User.is_active.desc(),
            Role.is_admin.desc(),
            Role.is_editor.desc(),
            User.login
        )
    )
    users = result.scalars().all()

    # Получаем все роли для выпадающего списка
    roles_result = await db.execute(
        select(Role)
        .order_by(Role.is_admin.desc(), Role.is_editor.desc(), Role.name)
    )
    roles = roles_result.scalars().all()

    # Уведомления
    success = request.query_params.get('success')
    error = request.query_params.get('error')

    return templates.TemplateResponse(
        'users.html',
        {
            'request': request,
            'users': users,
            'roles': roles,
            'user': current_user,
            'success': success,
            'error': error
        }
    )

@router.post('/')
async def user_create(
        request: Request,
        login: str = Form(...),
        email: str = Form(None),
        password: str = Form(...),
        role_id: UUID = Form(...),
        is_active: bool = Form(True),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Добавить пользователя"""
    login = login.strip()
    if len(login) < 3:
        return RedirectResponse(
            url='/users?error=Логин должен содержать минимум 3 символа',
            status_code=status.HTTP_303_SEE_OTHER
        )
    if len(login) > 100:
        return RedirectResponse(
            url='/users?error=Логин не должен превышать 100 символов',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка уникальности логина
    result = await db.execute(
        select(User).where(func.lower(User.login) == func.lower(login))
    )
    existing = result.scalar_one_or_none()
    if existing:
        return RedirectResponse(  # ← Исправлена опечатка "Пользовать" → "Пользователь"
            url=f'/users?error=Пользователь с логином "{login}" уже существует',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка уникальности email
    if email:
        email = email.strip()
        if email:
            result = await db.execute(
                select(User).where(func.lower(User.email) == func.lower(email))
            )
            existing_email = result.scalar_one_or_none()
            if existing_email:
                return RedirectResponse(
                    url=f'/users?error=Email "{email}" уже используется другим пользователем',
                    status_code=status.HTTP_303_SEE_OTHER
                )
    else:
        email = None

    # Валидация пароля
    if len(password) < 8:
        return RedirectResponse(
            url='/users?error=Пароль должен содержать минимум 8 символов',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка существования роли
    role = await role_crud.get(db, role_id)
    if not role:
        return RedirectResponse(
            url='/users?error=Выбранная роль не найдена',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Хэширование пароля
    hashed_password = get_password_hash(password)

    # Создание пользователя
    user_data = UserCreate(
        login=login,
        email=email,
        password=hashed_password,
        role_id=role_id,
        is_active=is_active
    )
    user = await user_crud.create(db, user_data)

    logger.info(f'Пользователь "{login}" создан администратором {current_user.login}')

    return RedirectResponse(
        url='/users?success=Пользователь успешно добавлен',
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post('/{user_id}')
async def user_update(
        user_id: UUID,
        request: Request,
        login: str = Form(...),
        email: str = Form(None),
        password: str = Form(None),
        role_id: UUID = Form(...),
        is_active: bool = Form(True),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Редактировать пользователя"""
    # Проверка существования
    user = await user_crud.get(db, user_id)
    if not user:
        return RedirectResponse(
            url='/users?error=Пользователь не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Защита от изменения себя (роли и статуса)
    if user.id == current_user.id:
        # Можно менять только пароль и email, но не роль и не статус
        if str(role_id) != str(current_user.role_id):
            return RedirectResponse(
                url='/users?error=Нельзя изменить свою роль',
                status_code=status.HTTP_303_SEE_OTHER
            )
        if not is_active:
            return RedirectResponse(
                url='/users?error=Нельзя деактивировать свою учётную запись',
                status_code=status.HTTP_303_SEE_OTHER
            )

    # Валидация логина
    login = login.strip()
    if len(login) < 3:
        return RedirectResponse(
            url='/users?error=Логин должен содержать минимум 3 символа',
            status_code=status.HTTP_303_SEE_OTHER
        )
    if len(login) > 100:
        return RedirectResponse(
            url='/users?error=Логин не должен превышать 100 символов',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка уникальности логина (исключая текущего пользователя)
    result = await db.execute(
        select(User).where(
            func.lower(User.login) == func.lower(login),
            User.id != user_id
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        return RedirectResponse(
            url=f'/users?error=Логин "{login}" уже используется другим пользователем',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Проверка уникальности email
    if email:
        email = email.strip()
        if email:
            result = await db.execute(
                select(User).where(
                    func.lower(User.email) == func.lower(email),
                    User.id != user_id
                )
            )
            existing_email = result.scalar_one_or_none()
            if existing_email:
                return RedirectResponse(
                    url=f'/users?error=Email "{email}" уже используется другим пользователем',
                    status_code=status.HTTP_303_SEE_OTHER
                )
    else:
        email = None

    # Валидация и хэширование пароля (если указан)
    hashed_password = None
    if password:
        if len(password) < 8:
            return RedirectResponse(
                url='/users?error=Пароль должен содержать минимум 8 символов',
                status_code=status.HTTP_303_SEE_OTHER
            )
        hashed_password = get_password_hash(password)

    # Проверка существования роли
    role = await role_crud.get(db, role_id)
    if not role:
        return RedirectResponse(
            url='/users?error=Выбранная роль не найдена',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Подготовка данных для обновления
    update_data = {
        "login": login,
        "email": email,
        "role_id": role_id,
        "is_active": is_active
    }

    # Добавляем пароль только если он был изменён
    if hashed_password:
        update_data["password"] = hashed_password

    # Создание схемы обновления
    user_data = UserUpdate(**update_data)
    updated = await user_crud.update(db, user_id, user_data)

    action = "обновлён" if not hashed_password else "обновлён с изменением пароля"
    logger.info(f'Пользователь "{user.login}" {action} администратором {current_user.login}')

    return RedirectResponse(
        url='/users?success=Пользователь успешно обновлён',
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post('/{user_id}/deactivate')
async def user_deactivate(
        user_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Деактивировать пользователя (мягкое удаление)"""
    # Проверка существования
    user = await user_crud.get(db, user_id)
    if not user:
        return RedirectResponse(
            url='/users?error=Пользователь не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Защита от деактивации себя
    if user.id == current_user.id:
        return RedirectResponse(
            url='/users?error=Нельзя деактивировать свою учётную запись',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Деактивация
    user_data = UserUpdate(is_active=False)
    updated = await user_crud.update(db, user_id, user_data)

    logger.info(f'Пользователь "{user.login}" деактивирован администратором {current_user.login}')

    return RedirectResponse(
        url='/users?success=Пользователь деактивирован',
        status_code=status.HTTP_303_SEE_OTHER
    )

@router.post('/{user_id}/activate')
async def user_activate(
        user_id: UUID,
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Активировать пользователя"""
    # Проверка существования
    user = await user_crud.get(db, user_id)
    if not user:
        return RedirectResponse(
            url='/users?error=Пользователь не найден',
            status_code=status.HTTP_303_SEE_OTHER
        )

    # Активация
    user_data = UserUpdate(is_active=True)
    updated = await user_crud.update(db, user_id, user_data)

    logger.info(f'Пользователь "{user.login}" активирован администратором {current_user.login}')

    return RedirectResponse(
        url='/users?success=Пользователь активирован',
        status_code=status.HTTP_303_SEE_OTHER
    )
