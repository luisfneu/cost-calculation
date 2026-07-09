"""venda_itens.insumo_baixado — marca se os insumos da encomenda já foram consumidos

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-09

IMPORTANTE: usar apenas op.add_column direto (sem batch_alter_table). A tabela
venda_itens tem uma FK para 'vendas_legacy' (tabela que não existe mais); recriar
a tabela via batch dispara NoSuchTableError. add_column direto não recria a tabela.
"""
import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "venda_itens",
        sa.Column("insumo_baixado", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("venda_itens", "insumo_baixado")
