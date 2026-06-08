# crud/workshop_user.py

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from crud.base import BaseCRUD
from models import WorkshopUser
from schemas import WorkshopUserCreate, WorkshopUserUpdate

class WorkshopUserCRUD(BaseCRUD[WorkshopUser, WorkshopUserCreate, WorkshopUserUpdate]):
    """CRUD для привязки пользователей к цехам"""

    def __init__(self):
        super().__init__(WorkshopUser)

    async def get_by_user_and_workshop(self, db: AsyncSession, user_id: UUID, workshop_id: UUID):
        """Получить привязку по пользователю и цеху"""
        result = await db.execute(
            select(self.model)
            .where(self.model.user_id == user_id, self.model.workshop_id == workshop_id)
        )

        return result.scalar_one_or_none()

    async def get_by_user(self, db: AsyncSession, user_id):
        """Получить привязку по пользователю"""
        result = await db.execute(
            select(self.model)
            .where(self.model.user_id == user_id)
        )

        return result.scalars().all()

    async def get_by_workshop(self, db: AsyncSession, workshop_id: UUID):
        """Получить привязку по пользователю и цеху"""
        result = await db.execute(
            select(self.model)
            .where(self.model.workshop_id == workshop_id)
        )

        return result.scalars().all()
