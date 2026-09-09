"""add_units_count_to_products

Revision ID: 5d00e674e5de
Revises: 1db2cacdf78a
Create Date: 2026-09-09 10:57:09.821383

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d00e674e5de'
down_revision: Union[str, Sequence[str], None] = '1db2cacdf78a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('products', sa.Column('units_count', sa.String(length=50), nullable=True, comment='Вложенность (количество единиц в упаковке), напр. "6шт" ({units_count})'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('products', 'units_count')
