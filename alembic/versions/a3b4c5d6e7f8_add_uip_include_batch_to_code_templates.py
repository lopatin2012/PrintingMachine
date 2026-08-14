"""Add uip_include_batch to code_templates

Revision ID: a3b4c5d6e7f8
Revises: a2b3c4d5e6f7
Create Date: 2026-08-14 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Флаг «включать партию в УИП» — свойство шаблона печати.
    op.add_column(
        'code_templates',
        sa.Column('uip_include_batch', sa.Boolean(), nullable=False,
                  server_default=sa.true(), comment='Включать партию в УИП'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('code_templates', 'uip_include_batch')
