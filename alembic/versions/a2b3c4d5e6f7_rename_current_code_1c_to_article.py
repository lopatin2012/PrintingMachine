"""Rename current_code_1c to article in products

Артикул продукта — это текущий код 1С (поле article дублировало current_code_1c).
Колонка current_code_1c переименовывается в article.

Revision ID: a2b3c4d5e6f7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-14 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('products', 'current_code_1c', new_column_name='article')
    # Переименовываем связанное ограничение уникальности (имя по умолчанию PostgreSQL).
    op.execute(
        'ALTER TABLE products RENAME CONSTRAINT '
        'products_current_code_1c_key TO products_article_key'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        'ALTER TABLE products RENAME CONSTRAINT '
        'products_article_key TO products_current_code_1c_key'
    )
    op.alter_column('products', 'article', new_column_name='current_code_1c')
