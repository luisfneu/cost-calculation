"""parcelas (crediario)

Revision ID: 510cf3f0f0eb
Revises: 155cd34cf625
Create Date: 2026-07-02 23:06:52.783482

Migração enxuta: cria a tabela 'parcelas' (crediário). Os alter_column de
NOT NULL sugeridos pelo autogenerate foram removidos (divergências cosméticas
do schema antigo — não recriamos tabelas à toa).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '510cf3f0f0eb'
down_revision = '155cd34cf625'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'parcelas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('venda_id', sa.Integer(), nullable=False),
        sa.Column('numero', sa.Integer(), nullable=False),
        sa.Column('total', sa.Integer(), nullable=False),
        sa.Column('valor', sa.Float(), nullable=False),
        sa.Column('vencimento', sa.Date(), nullable=True),
        sa.Column('pago', sa.Boolean(), nullable=False),
        sa.Column('pago_em', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['venda_id'], ['vendas.id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('parcelas')
