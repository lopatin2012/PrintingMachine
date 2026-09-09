"""add_label_print_fields_to_products

Revision ID: 1db2cacdf78a
Revises: a7b8c9d0e1f2
Create Date: 2026-09-09 09:22:36.679940

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1db2cacdf78a'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('products', sa.Column('name_line1', sa.String(length=200), nullable=True, comment='Название на этикетке, строка 1 ({product_name_line1})'))
    op.add_column('products', sa.Column('name_line2', sa.String(length=200), nullable=True, comment='Название на этикетке, строка 2 ({product_name_line2})'))
    op.add_column('products', sa.Column('tu_number', sa.String(length=100), nullable=True, comment='Номер ТУ ({tu})'))
    op.add_column('products', sa.Column('weight', sa.String(length=50), nullable=True, comment='Вес (масса нетто), напр. "40г" ({weight})'))
    op.add_column('products', sa.Column('fat_content', sa.String(length=50), nullable=True, comment='Жирность, напр. "16%" ({fat})'))
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('products', 'fat_content')
    op.drop_column('products', 'weight')
    op.drop_column('products', 'tu_number')
    op.drop_column('products', 'name_line2')
    op.drop_column('products', 'name_line1')
