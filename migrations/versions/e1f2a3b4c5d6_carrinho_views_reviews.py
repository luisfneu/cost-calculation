"""clientes.carrinho_json/carrinho_em + pecas.views + tabela avaliacoes

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-11

- carrinho_json/carrinho_em: carrinho do cliente logado persistido (CRM de
  carrinhos abandonados + continuidade entre aparelhos).
- pecas.views: contador de visualizações da página pública da peça.
- avaliacoes: reviews de peça por cliente (moderadas no ERP).
IMPORTANTE: op.add_column direto (sem batch) — padrão do projeto (FK legada).
create_table é seguro (tabela nova).
"""
import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clientes",
                  sa.Column("carrinho_json", sa.Text(), nullable=False, server_default=""))
    op.add_column("clientes", sa.Column("carrinho_em", sa.DateTime(), nullable=True))
    op.add_column("pecas",
                  sa.Column("views", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "avaliacoes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("peca_id", sa.Integer(), sa.ForeignKey("pecas.id"), nullable=False),
        sa.Column("cliente_id", sa.Integer(), sa.ForeignKey("clientes.id"), nullable=False),
        sa.Column("nota", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("texto", sa.Text(), nullable=False, server_default=""),
        sa.Column("aprovado", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("criado_em", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("peca_id", "cliente_id", name="uq_avaliacao_peca_cliente"),
    )


def downgrade():
    op.drop_table("avaliacoes")
    op.drop_column("pecas", "views")
    op.drop_column("clientes", "carrinho_em")
    op.drop_column("clientes", "carrinho_json")
