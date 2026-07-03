"""cupom cliente_id

Revision ID: 773a10bece6d
Revises: f75b77946637
Create Date: 2026-07-03 14:34:34.738320

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '773a10bece6d'
down_revision = 'f75b77946637'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('cupons', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cliente_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_cupons_cliente', 'clientes', ['cliente_id'], ['id']
        )


def downgrade():
    with op.batch_alter_table('cupons', schema=None) as batch_op:
        batch_op.drop_constraint('fk_cupons_cliente', type_='foreignkey')
        batch_op.drop_column('cliente_id')
