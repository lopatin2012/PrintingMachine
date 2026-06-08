# crud/code_template.py

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from crud.base import BaseCRUD
from models import CodeTemplate
from schemas import CodeTemplateCreate, CodeTemplateUpdate


class CodeTemplateCRUD(BaseCRUD[CodeTemplate, CodeTemplateCreate, CodeTemplateUpdate]):
    """CRUD для шаблонов печати"""

    def __init__(self):
        super().__init__(CodeTemplate)

    async def get_active_templates_by_printer(self, db: AsyncSession, printer_id: UUID):
        """Получить активные шаблоны для принтера"""
        result = await db.execute(
            select(self.model).where(
                self.model.printer_id == printer_id,
                self.model.is_active == True
            )
        )
        return result.scalars().all()

    async def get_templates_by_product(self, db: AsyncSession, product_id: UUID):
        """Получить все шаблоны для продукта"""
        result = await db.execute(
            select(self.model).where(self.model.product_id == product_id)
        )
        return result.scalars().all()
