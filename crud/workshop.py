# crud/workshop.py

from sqlalchemy.ext.asyncio import AsyncSession
from crud.base import BaseCRUD
from models import Workshop
from schemas import WorkshopCreate, WorkshopUpdate

class WorkshopCRUD(BaseCRUD[Workshop, WorkshopCreate, WorkshopUpdate]):
    def __init__(self):
        super().__init__(Workshop)

    async def get_by_name(self, db: AsyncSession, name: str):
        """Получить по имени"""
        from sqlalchemy import select

        result = await db.execute(
            select(self.model).where(self.model.name == name)
        )

        return result.scalar_one_or_none()
