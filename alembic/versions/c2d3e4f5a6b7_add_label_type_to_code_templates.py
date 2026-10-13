"""label_type — назначение шаблона (потребительская/групповая упаковка)

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-10-13 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Назначение шаблона: unit — этикетка потребительской упаковки (GTIN единицы),
    # group — этикетка групповой упаковки/набора (GTIN упаковки). По умолчанию
    # group, чтобы уже заведённые шаблоны остались на прежнем поведении.
    op.add_column(
        'code_templates',
        sa.Column('label_type', sa.String(length=20), nullable=False,
                  server_default='group',
                  comment='Назначение шаблона: unit — потребительская упаковка, group — групповая упаковка/набор'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('code_templates', 'label_type')
