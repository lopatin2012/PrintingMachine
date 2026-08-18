"""is_print_gtin_unit — печать DataMatrix-кодов из внешнего сервиса

Revision ID: a7b8c9d0e1f2
Revises: a6b7c8d9e0f1
Create Date: 2026-08-18 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'a6b7c8d9e0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Флаг «печатать DataMatrix-коды из внешнего сервиса» — свойство шаблона.
    # По умолчанию выключен.
    op.add_column(
        'code_templates',
        sa.Column('is_print_gtin_unit', sa.Boolean(), nullable=False,
                  server_default=sa.text('false'),
                  comment='Печатать DataMatrix-коды из внешнего сервиса (плейсхолдер {datamatrix})'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('code_templates', 'is_print_gtin_unit')
