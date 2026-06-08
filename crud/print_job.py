# crud/print_job.py

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from crud.base import BaseCRUD
from models import PrintJob
from schemas import PrintJobCreate, PrintJobUpdate


class PrintJobCRUD(BaseCRUD[PrintJob, PrintJobCreate, PrintJobUpdate]):
    """CRUD для заданий на печать"""

    def __init__(self):
        super().__init__(PrintJob)

    async def get_user_jobs(
            self,
            db: AsyncSession,
            user_id: UUID,
            limit: int = 50,
            status_filter: str = None
    ):
        """Получить задания пользователя (последние)"""
        query = select(self.model).where(self.model.user_id == user_id)

        if status_filter:
            query = query.where(self.model.status == status_filter)

        query = query.order_by(desc(self.model.created_at)).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    async def get_active_jobs(self, db: AsyncSession, limit: int = 100):
        """Получить все активные задания (для админа)"""
        query = select(self.model).where(
            self.model.status.in_(['pending', 'processing'])
        ).order_by(self.model.created_at)
        result = await db.execute(query.limit(limit))
        return result.scalars().all()
