"""external_uuid — привязка продукта к UUID во внешнем сервисе кодов

Revision ID: b1c2d3e4f5a6
Revises: a7b8c9d0e1f2
Create Date: 2026-10-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # UUID продукта во внешнем сервисе кодов (СУЗ/СУП). По нему при печати
    # запрашиваются DataMatrix-коды (плейсхолдер {datamatrix}).
    op.add_column(
        'products',
        sa.Column(
            'external_uuid', sa.String(length=100), nullable=True,
            comment='UUID продукта во внешнем сервисе кодов (для DataMatrix-кодов по UUID)',
        ),
    )
    op.create_index(
        'ix_products_external_uuid', 'products', ['external_uuid'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_products_external_uuid', table_name='products')
    op.drop_column('products', 'external_uuid')
