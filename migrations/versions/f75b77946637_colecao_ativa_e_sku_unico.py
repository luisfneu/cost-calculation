"""colecao ativa e sku unico

Revision ID: f75b77946637
Revises: 21ee6ddb6c8d
Create Date: 2026-07-03 11:12:58.863789

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f75b77946637'
down_revision = '21ee6ddb6c8d'
branch_labels = None
depends_on = None


def upgrade():
    # 1) Coleção: campo ativa/inativa (default ativa).
    with op.batch_alter_table('colecoes', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('ativa', sa.Boolean(), nullable=False, server_default=sa.text('1'))
        )

    # 2) SKU único gerado pelo id: backfill SH-00000000 em todas as peças.
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE pecas SET sku = 'SH-' || substr('00000000' || id, -8, 8)"
    ))

    # 3) Índice único no SKU.
    with op.batch_alter_table('pecas', schema=None) as batch_op:
        batch_op.create_unique_constraint('uq_pecas_sku', ['sku'])


def downgrade():
    with op.batch_alter_table('pecas', schema=None) as batch_op:
        batch_op.drop_constraint('uq_pecas_sku', type_='unique')
    with op.batch_alter_table('colecoes', schema=None) as batch_op:
        batch_op.drop_column('ativa')
