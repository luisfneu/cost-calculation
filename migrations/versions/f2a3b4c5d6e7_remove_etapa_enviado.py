"""remove a etapa 'enviado' do stepper do cliente

A etapa `enviado` ("Pedido enviado") saiu do grupo Envio. Vendas que estavam
nela passam para `na_transportadora` ("Entregue à transportadora"), a etapa
seguinte do mesmo grupo. Só dados — sem mudança de schema.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""
from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE vendas SET etapa_pedido = 'na_transportadora' "
        "WHERE etapa_pedido = 'enviado'"
    )


def downgrade():
    op.execute(
        "UPDATE vendas SET etapa_pedido = 'enviado' "
        "WHERE etapa_pedido = 'na_transportadora'"
    )
