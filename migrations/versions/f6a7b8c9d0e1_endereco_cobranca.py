"""enderecos.cobranca — papel de endereço de cobrança (além do principal/entrega)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-10

Um endereço pode ser principal (entrega) e/ou de cobrança — os dois papéis
podem apontar para o mesmo endereço. Backfill: o principal atual também vira
o de cobrança (antes só havia um endereço por cliente).
"""
import sqlalchemy as sa
from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("enderecos",
                  sa.Column("cobranca", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.get_bind().execute(sa.text("UPDATE enderecos SET cobranca = 1 WHERE principal = 1"))


def downgrade():
    op.drop_column("enderecos", "cobranca")
