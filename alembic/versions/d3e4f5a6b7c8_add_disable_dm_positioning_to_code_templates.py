"""disable_dm_positioning — выключение позиционирования DataMatrix в редакторе

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-11-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, Sequence[str], None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Флаг «выключить позиционирование DataMatrix» — свойство шаблона.
    # При включении редактор не показывает рамки и координаты DataMatrix
    # (и не меняет ^FO), в предпросмотре координаты тоже убираются.
    # По умолчанию выключен (позиционирование включено).
    op.add_column(
        'code_templates',
        sa.Column('disable_dm_positioning', sa.Boolean(), nullable=False,
                  server_default=sa.text('false'),
                  comment='Выключить позиционирование DataMatrix в редакторе (не показывать координаты и рамки)'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('code_templates', 'disable_dm_positioning')
