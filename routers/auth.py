# routers/auth.py

from datetime import timedelta

from fastapi import APIRouter, Request, Form, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models import User, Role
from auth_utils import get_password_hash, verify_password

from crud.user import UserCRUD

from templates_config import templates
from security import create_access_token, oauth2_scheme, get_current_admin

router = APIRouter()
user_crud = UserCRUD()

# Конфигурация токена
ACCESS_TOKEN_EXPIRE_MINUTES = 1500

@router.get('/register', response_class=HTMLResponse)
async def register_page(
        request: Request,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)
):
    """Страница регистрации. Отображение."""
    result = await db.execute(select(Role))
    roles = result.scalars().all()

    return templates.TemplateResponse(
        'register.html',
        {
            'request': request,
            'roles': roles
        }
    )

@router.post('/register')
async def register(
        request: Request,
        login: str = Form(...),
        email: str = Form(...),
        password: str = Form(...),
        confirm_password: str = Form(...),
        role_id: str = Form(...),
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_admin)

):
    """Страница регистрации. Обработка."""

    # Проверка пароля.
    if password != confirm_password:
        return templates.TemplateResponse(
            'register.html',
            {
                'request': request,
                'error': 'Пароли не совпадают',
                'login': login,
                'email': email
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            'register.html',
            {
                'request': request,
                'error': 'Пароль должен содержать минимум 8 символов',
                'login': login,
                'email': email
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    # Создание пользователя.
    hashed_password = get_password_hash(password)
    user = User(
        login=login,
        email=email,
        password=hashed_password,
        role_id=role_id
    )
    db.add(user)
    await db.commit()

    return templates.TemplateResponse(
        'register.html',
        {
            'request': request,
            'success': 'Регистрация завершена успешно!',
            'show_login': True
        },
        status_code=status.HTTP_200_OK
    )

@router.get('/user_login', response_class=HTMLResponse)
async def login_page(request: Request):
    """Страница входа."""

    # Проверяем пользователя, был ли ранее вход в систему.

    return templates.TemplateResponse(
        'login.html',
        {'request': request}
    )

@router.post('/user_login')
async def login(
        request: Request,
        login: str = Form(...),
        password: str = Form(...),
        db: AsyncSession = Depends(get_db)
):
    """Вход в систему по логину"""

    user = await user_crud.get_by_login(db, login)

    if not user or not verify_password(password, user.password):
        return templates.TemplateResponse(
            'login.html',
            {
                'request': request,
                'error': 'Неверный логин или пароль',
                'login': login
            },
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    if not user.is_active:
        return templates.TemplateResponse(
            'login.html',
            {
                'request': request,
                'error': 'Учётная запись отключена',
                'login': login
            },
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    # Создаём JWT токен.
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={'sub': str(user.id)},
        expires_delta=access_token_expires
    )

    # Перенаправление с установкой куки.
    response = RedirectResponse(
        url='/',
        status_code=status.HTTP_303_SEE_OTHER
    )
    response.set_cookie(
        key='access_token',
        value=f'Bearer {access_token}',
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        secure=False,
        samesite='lax'
    )

    return response

@router.post('/user_logout')
async def logout(request: Request):
    """Выход из системы"""
    response = RedirectResponse(url='/', status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key='access_token')
    return response

@router.get('/protected', response_class=HTMLResponse)
async def protected_route(
        request: Request,
        current_user: User = Depends(oauth2_scheme)
):
    """Защищённый маршрут для теста"""
    return templates.TemplateResponse(
        'protected.html',
        {
            'request': request,
            'user': current_user
        }
    )
