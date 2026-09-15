"""Add external_uuid column to products

Revision ID: b1c2d3e4f5a6
Revises: 5d00e674e5de
Create Date: 2026-09-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = '5d00e674e5de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # UUID продукта во внешнем сервисе кодов: по нему запрашиваются
    # DataMatrix-коды (GET /codes/api/get_codes_by_product/?uuid_product=...).
    op.add_column(
        'products',
        sa.Column('external_uuid', sa.String(length=64), nullable=True,
                  comment='UUID продукта во внешнем сервисе кодов (get_codes_by_product)'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('products', 'external_uuid')
