# crud/role.py

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from crud.base import BaseCRUD
from models import Role
from schemas import RoleCreate, RoleUpdate

class RoleCRUD(BaseCRUD[Role, RoleCreate, RoleUpdate]):
    """CRUD ролей"""

    def __init__(self):
        super().__init__(Role)

    async def get_by_name(self, db: AsyncSession, name: str) -> Role | None:
        """Получить роль по имени"""

        result = await db.execute(
            select(self.model).where(self.model.name == name)
        )

        return result.scalar_one_or_none()