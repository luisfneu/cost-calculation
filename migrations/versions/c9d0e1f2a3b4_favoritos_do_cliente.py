"""clientes.favoritos_json — favoritos da vitrine sincronizados na conta

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-11

Lista de ids de peças (JSON) favoritadas pelo cliente logado. Antes ficava só
no localStorage do navegador — trocar de aparelho perdia tudo.
IMPORTANTE: op.add_column direto (sem batch) — padrão do projeto por causa da
FK legada de venda_itens (batch recria tabela e quebra).
"""
import sqlalchemy as sa
from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clientes",
                  sa.Column("favoritos_json", sa.Text(), nullable=False, server_default=""))


def downgrade():
    op.drop_column("clientes", "favoritos_json")
