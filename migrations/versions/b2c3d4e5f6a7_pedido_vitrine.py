"""pedido pela vitrine: lead.pedido_json, venda.lead_id, venda_item.produzir

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-04 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # ATENÇÃO: usar apenas ALTER TABLE ADD COLUMN (não recriar tabelas). A tabela
    # venda_itens tem uma FK legada para 'vendas_legacy' (inexistente) que quebra
    # qualquer recriação em modo batch. A FK do lead fica só no modelo (o SQLite
    # não força FKs aqui; o relacionamento funciona pela coluna).
    op.add_column('leads', sa.Column('pedido_json', sa.Text(), nullable=True))
    op.add_column('vendas', sa.Column('lead_id', sa.Integer(), nullable=True))
    op.add_column('venda_itens',
                  sa.Column('produzir', sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column('venda_itens',
                  sa.Column('produzido', sa.Boolean(), nullable=False, server_default=sa.text("0")))

    # Encomendas legadas (venda tipo='encomenda' sem estoque baixado): marca seus
    # itens como "a produzir" para aparecerem na nova tela de Encomendas.
    op.execute(
        "UPDATE venda_itens SET produzir = 1 WHERE venda_id IN "
        "(SELECT id FROM vendas WHERE tipo = 'encomenda' AND estoque_baixado = 0)"
    )


def downgrade():
    op.drop_column('venda_itens', 'produzido')
    op.drop_column('venda_itens', 'produzir')
    op.drop_column('vendas', 'lead_id')
    op.drop_column('leads', 'pedido_json')
