# crud/printer.py

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from crud.base import BaseCRUD
from models import Printer
from schemas import PrinterCreate, PrinterUpdate

class PrinterCRUD(BaseCRUD[Printer, PrinterCreate, PrinterUpdate]):
    def __init__(self):
        super().__init__(Printer)

    async def get_by_name(self, db: AsyncSession, name: str):
        """Получить по имена"""

        result = await db.execute(
            select(self.model).where(self.model.name == name)
        )

        return result.scalar_one_or_none()

    async def get_by_ip(self, db: AsyncSession, ip_address: str):
        """Получить по ip адресу"""

        result = await db.execute(
            select(self.model).where(self.model.ip_address == ip_address)
        )

        return result.scalar_one_or_none()

    async def get_printers_by_line(self, db: AsyncSession, line_id: UUID):
        """Получить все принтеры линии"""
        result = await db.execute(
            select(self.model).where(self.model.line_id == line_id)
        )

        return result.scalars().all()
