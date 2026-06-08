# crud/line.py

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from crud.base import BaseCRUD
from models import Line
from schemas import LineCreate, LineUpdate


class LineCRUD(BaseCRUD[Line, LineCreate, LineUpdate]):
    def __init__(self):
        super().__init__(Line)

    async def get_by_name(self, db: AsyncSession, name: str):
        """Получить по имени"""
        from sqlalchemy import select

        result = await db.execute(
            select(self.model).where(self.model.name == name)
        )

        return result.scalar_one_or_none()

    async def get_lines_by_workshop(self, db: AsyncSession, workshop_id: UUID) -> list[Line]:
        """Получить все линии цеха"""
        result = await db.execute(
            select(self.model).where(self.model.workshop_id == workshop_id)
        )
        return result.scalars().all()
