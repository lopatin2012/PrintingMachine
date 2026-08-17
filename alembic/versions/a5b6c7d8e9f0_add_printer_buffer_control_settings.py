"""Add printer buffer control settings (buffer_limit, batch_size)

Revision ID: a5b6c7d8e9f0
Revises: a4b5c6d7e8f9
Create Date: 2026-08-17 23:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5b6c7d8e9f0'
down_revision: Union[str, Sequence[str], None] = 'a4b5c6d7e8f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Контроль очереди принтера: максимум этикеток «в полёте» и размер пачки.
    op.add_column(
        'printers',
        sa.Column('buffer_limit', sa.Integer(), nullable=False,
                  server_default='25', comment='Макс. этикеток в очереди принтера'),
    )
    op.add_column(
        'printers',
        sa.Column('batch_size', sa.Integer(), nullable=False,
                  server_default='5', comment='Отправка пачками по N этикеток'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('printers', 'batch_size')
    op.drop_column('printers', 'buffer_limit')
