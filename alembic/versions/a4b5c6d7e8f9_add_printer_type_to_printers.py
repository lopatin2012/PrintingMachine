"""Add printer_type to printers

Revision ID: a4b5c6d7e8f9
Revises: a3b4c5d6e7f8
Create Date: 2026-08-14 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, Sequence[str], None] = '1805bce1d329'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Тип принтера: zebra | tsc (по умолчанию zebra).
    op.add_column(
        'printers',
        sa.Column('printer_type', sa.String(length=20), nullable=False,
                  server_default='zebra', comment='Тип принтера (zebra/tsc)'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('printers', 'printer_type')
