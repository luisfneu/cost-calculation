"""vendas.etapa_pedido — jornada do pedido para o cliente (stepper)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-10

Coluna independente do `status` do ERP. Backfill a partir do status atual.
IMPORTANTE: op.add_column direto (sem batch) — venda_itens tem FK legada p/
vendas_legacy; recriar a tabela via batch quebraria. Aqui é a tabela `vendas`,
mas mantemos o padrão add_column direto por segurança.
"""
import sqlalchemy as sa
from alembic import op

revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("vendas",
                  sa.Column("etapa_pedido", sa.String(length=20), nullable=False, server_default="recebido"))
    conn = op.get_bind()
    # Backfill aproximado a partir do status/pago atuais.
    conn.execute(sa.text("UPDATE vendas SET etapa_pedido='entregue' WHERE status='entregue'"))
    conn.execute(sa.text("UPDATE vendas SET etapa_pedido='em_transporte' WHERE status='enviado'"))
    conn.execute(sa.text("UPDATE vendas SET etapa_pedido='pgto_aprovado' WHERE status IN ('realizado','pago','crediario') AND pago=1"))
    conn.execute(sa.text("UPDATE vendas SET etapa_pedido='aguard_pgto' WHERE status IN ('realizado','pago','crediario') AND pago=0"))
    conn.execute(sa.text("UPDATE vendas SET etapa_pedido='recebido' WHERE status='pre-pedido'"))


def downgrade():
    op.drop_column("vendas", "etapa_pedido")
