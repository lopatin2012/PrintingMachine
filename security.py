# security.py

import os
import uuid
from datetime import datetime, timedelta
from typing import Optional, Any, Coroutine

from jose import jwt, JWTError

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import Response
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from models import User
from crud.user import UserCRUD
from database import get_db

user_crud = UserCRUD()

SECRET_KEY = os.getenv("SECRET_KEY", "90d0574d11647998cfe986d20553fa00")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 600

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="user_login", auto_error=False)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Создать токен доступа"""
    to_encode = data.copy()
    expire = datetime.now() + (expires_delta or timedelta(minutes=15))
    to_encode.update({'exp': expire})

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user_optional(
        request: Request,
        db: AsyncSession = Depends(get_db)
) -> User | None:
    """Текущий пользователь из куки или None (для гостевых страниц)."""
    token = request.cookies.get('access_token')

    if not token:
        return None

    # Чистим токен.
    token = token.replace('Bearer ', '')

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str = payload.get('sub')

        if user_id_str is None:
            return None

        # Преобразуем строку в UUID
        try:
            user_id = uuid.UUID(user_id_str)
        except ValueError:
            return None

    except JWTError:
        return None

    # Получаем пользователя из БД.
    result = await user_crud.get(db, user_id)

    return result


async def get_current_user(
        current_user: User | None = Depends(get_current_user_optional)
) -> User:
    """Текущий пользователь; без валидной сессии — редирект на вход (302).

    Защищённые страницы и методы не должны падать с 500 при отсутствии или
    просрочке токена — гостя отправляем на страницу входа. Гостевым остаётся
    главная (там нужен None) и polling-эндпоинты, использующие
    :func:`get_current_user_optional`.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={'Location': 'user_login'}
        )
    return current_user

async def get_current_admin(
        current_user: User = Depends(get_current_user)
):
    """Проверка прав админа"""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            headers={'Location': 'user_login'}
        )

    if not current_user.role or not current_user.role.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Требуются права админа'
        )

    return current_user
