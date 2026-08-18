"""uip_include_batch по умолчанию выключен (false)

Revision ID: a6b7c8d9e0f1
Revises: a5b6c7d8e9f0
Create Date: 2026-08-18 10:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a6b7c8d9e0f1'
down_revision: Union[str, Sequence[str], None] = 'a5b6c7d8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # «Включать партию в УИП» по умолчанию выключено (было включено).
    # Существующие шаблоны не меняются — изменяется только значение по умолчанию
    # для новых шаблонов.
    op.alter_column('code_templates', 'uip_include_batch',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('false'),
               existing_server_default=sa.text('true'),
               comment='Включать партию в УИП',
               existing_nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('code_templates', 'uip_include_batch',
               existing_type=sa.BOOLEAN(),
               server_default=sa.text('true'),
               existing_server_default=sa.text('false'),
               comment='Включать партию в УИП',
               existing_nullable=False)
