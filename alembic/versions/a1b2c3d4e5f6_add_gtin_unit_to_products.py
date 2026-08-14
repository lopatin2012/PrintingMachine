"""Add gtin_unit column to products

Revision ID: a1b2c3d4e5f6
Revises: fe21ba439272
Create Date: 2026-08-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'fe21ba439272'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # GTIN единицы продукции (для УИП/DataMatrix).
    op.add_column(
        'products',
        sa.Column('gtin_unit', sa.String(length=50), nullable=True, comment='GTIN единицы продукции (для УИП/DataMatrix)'),
    )
    op.create_unique_constraint('uq_products_gtin_unit', 'products', ['gtin_unit'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_products_gtin_unit', 'products', type_='unique')
    op.drop_column('products', 'gtin_unit')
