# crud/product.py

from sqlalchemy.ext.asyncio import  AsyncSession
from sqlalchemy import select, func
from crud.base import BaseCRUD
from models import Product
from schemas import ProductCreate, ProductUpdate

class ProductCRUD(BaseCRUD[Product, ProductCreate, ProductUpdate]):
    """CRUD для продукта"""

    def __init__(self):
        super().__init__(Product)

    async def get_by_code_1c(self, db: AsyncSession, code_1c: str) -> Product | None:
        """Получить продукт по 1С"""
        result = await db.execute(
            select(self.model)
            .where(func.lower(self.model.current_code_1c) == func.lower(code_1c))
        )

        return result.scalar_one_or_none()

    async def get_by_gtin(self, db: AsyncSession, gtin: str) -> Product | None:
        """Получить продукт по GTIN"""
        result = await db.execute(
            select(self.model)
            .where(func.lower(self.model.gtin) == func.lower(gtin))
        )

        return result.scalar_one_or_none()
