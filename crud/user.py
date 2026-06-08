# crud/user.py

from sqlalchemy.ext.asyncio import AsyncSession
from crud.base import BaseCRUD
from models import User
from schemas import UserCreate, UserUpdate

class UserCRUD(BaseCRUD[User, UserCreate, UserUpdate]):
    def __init__(self):
        super().__init__(User)

    async def get_by_email(self, db: AsyncSession, email: str):
        """Получить по почте"""
        from sqlalchemy import select

        result = await db.execute(
            select(self.model).where(self.model.email == email)
        )

        return result.scalar_one_or_none()

    async def get_by_login(self, db: AsyncSession, login: str, is_active: bool = True):
        """Получить по логину"""
        from sqlalchemy import select

        result = await db.execute(
            select(self.model).where(
                self.model.login == login
                and
                self.model.is_active == is_active
            )
        )

        return result.scalar_one_or_none()
