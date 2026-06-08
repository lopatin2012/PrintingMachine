# crud/base.py

from typing import Type, TypeVar, Generic, Optional, List, Any, Coroutine, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, Row, RowMapping, func
from sqlalchemy.exc import SQLAlchemyError

from pydantic import BaseModel
from sqlalchemy.testing.config import db_opts

ModelType = TypeVar('ModelType')
CreateSchemaType = TypeVar('CreateSchemaType', bound=BaseModel)
UpdateSchemaType = TypeVar('UpdateSchemaType', bound=BaseModel)

class BaseCRUD(Generic[ModelType, CreateSchemaType, UpdateSchemaType]):
    """
    Базовый класс.
    """

    def __init__(self, model: Type[ModelType]):
        self.model = model

    async def get(self, db: AsyncSession, id: UUID) -> Optional[ModelType]:
        """
        Получить запись по id.
        :param db: Асинхронная сессия.
        :param id: id записи.
        :return:
        """
        result = await db.execute(
            select(self.model).where(self.model.id == id)
        )

        return result.scalar_one_or_none()

    async def get_multi(
            self,
            db: AsyncSession,
            skip: int = 0,
            limit: int = 100,
            filters: dict = None
    ) -> Sequence[Row[Any] | RowMapping]:
        """Получить записи по фильтрации"""
        query = select(self.model)

        # Применяем фильтры, если они были указаны.
        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    query = query.where(getattr(self.model, key) == value)

        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        return result.scalars().all()

    async def create(
            self,
            db: AsyncSession,
            obj_in: CreateSchemaType
    ):
        """Создание новой записи."""
        obj_data = obj_in.model_dump()
        db_obj = self.model(**obj_data)

        db.add(db_obj)

        try:
            await db.commit()
            await db.refresh(db_obj)
            return db_obj

        except SQLAlchemyError:
            await db.rollback()
            raise

    async def update(
            self,
            db: AsyncSession,
            id: UUID,
            obj_in: UpdateSchemaType
    ):
        """Обновить запись по ID."""
        result = await db.execute(
            select(self.model).where(self.model.id == id)
        )
        db_obj = result.scalar_one_or_none()

        if not db_obj:
            return None

        update_data = obj_in.model_dump(exclude_unset=True)

        for field, value in update_data.items():
            setattr(db_obj, field, value)

        try:
            await db.commit()
            await db.refresh(db_obj)
            return db_obj

        except SQLAlchemyError:
            await db.rollback()
            raise

    async def delete(
            self,
            db: AsyncSession,
            id: UUID
    ):
        """Удаление записи по ID."""
        result = await db.execute(
            select(self.model).where(self.model.id == id)
        )

        db_obj = result.scalar_one_or_none()

        if not db_obj:
            return False

        await db.delete(db_obj)

        try:
            await db.commit()
            return True

        except SQLAlchemyError:
            await db.rollback()
            raise

    async def exists(
            self,
            db: AsyncSession,
            id: UUID
    ) -> bool:
        """Проверить существование записи по ID."""

        result = await db.execute(
            select(self.model.id).where(self.model.id == id)
        )

        return result.scalar_one_or_none() is not None

    async def count(
            self,
            db: AsyncSession,
            filters: dict = None
    ):
        """Посчитать количество записей по фильтру."""
        query = select(func.count()).select_from(self.model)

        if filters:
            for key, value in filters.items():
                query = query.where(getattr(self.model, key) == value)

        result = await db.execute(query)
        return len(result.scalars().all())

    async def get_paginated(
            self,
            db: AsyncSession,
            skip: int = 0,
            limit: int = 100,
            filters: dict = None
    ):
        """Получить пагинированный результат"""

        items = await self.get_multi(db, skip=skip, limit=limit, filters=filters)

        total = await self.count(db, filters=filters)

        return {
            'items': items,
            'total': total,
            'skip': skip,
            'limit': limit,
            'has_more': skip + limit < total
        }
