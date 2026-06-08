# database.py

import os
import logging

from sqlalchemy import select
from sqlalchemy.ext.declarative import  declarative_base
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from auth_utils import get_password_hash

from dotenv import load_dotenv

# Импорт переменных.
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)

logger = logging.getLogger(__name__)

# Загрузка данных из .env.
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'database')

print([DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME])

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)


engine = create_async_engine(DATABASE_URL)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def init_db(_engine):
    from models import Role, User

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(_engine) as session:
        async with session.begin():
            # Создание базовых ролей.
            roles = [
                {'name': 'admin', 'description': 'Администратор', 'is_admin': True, 'is_editor': True},
                {'name': 'editor', 'description': 'Редактор', 'is_admin': False, 'is_editor': True},
                {'name': 'user', 'description': 'Пользователь', 'is_admin': False, 'is_editor': False}
            ]

            created_roles = {}

            for role_data in roles:
                result = await session.execute(
                    select(Role).where(Role.name == role_data['name'])
                )
                existing_role = result.scalar_one_or_none()

                if existing_role is None:
                    role = Role(**role_data)
                    session.add(role)
                    await session.flush()
                    created_roles[role_data['name']] = role
                    logger.info(f'Создана роль: {role_data["name"]}')
                else:
                    created_roles[role_data['name']] = existing_role

            admin_login = os.getenv('ADMIN_LOGIN', 'admin')
            admin_password = os.getenv('ADMIN_PASSWORD', 'admin')
            admin_email = os.getenv('ADMIN_EMAIL', 'admin@example.ru')

            result = await session.execute(
                select(User).where(User.login == admin_login)
            )
            existing_admin = result.scalar_one_or_none()

            if not existing_admin:
                hashed_password = get_password_hash(admin_password)

                admin_user = User(
                    login=admin_login,
                    email=admin_email,
                    password=hashed_password,
                    role_id=created_roles['admin'].id,
                    is_active=True
                )
                session.add(admin_user)
                await session.flush()

                logger.info(
                    f'Создан администратор: логин="{admin_login}", email="{admin_email}", '
                    f'роль="admin" (ID: {admin_user.id})'
                )

                # Важное предупреждение о смене пароля
                if admin_password == 'admin':
                    logger.error(
                        '❗❗❗ ВНИМАНИЕ: Используется стандартный пароль "admin"! '
                        'Немедленно смените пароль после первого входа в систему!'
                    )
            else:
                logger.info(
                    f'Администратор с логином "{admin_login}" уже существует (ID: {existing_admin.id})'
                )
            await session.commit()