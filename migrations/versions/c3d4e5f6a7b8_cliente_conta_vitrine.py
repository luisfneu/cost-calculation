"""conta do cliente na vitrine: clientes.email/senha_hash/aceita_novidades

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-06 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    # Só ADD COLUMN direto (mesma armadilha da FK legada de venda_itens: nada de
    # batch/recriação de tabela). O índice único do e-mail é criado à parte para
    # não recriar 'clientes'. E-mail NULL é permitido (clientes só de balcão);
    # o SQLite trata múltiplos NULL como distintos, então o unique não conflita.
    op.add_column('clientes', sa.Column('email', sa.String(length=160), nullable=True))
    op.add_column('clientes',
                  sa.Column('senha_hash', sa.String(length=255), nullable=False, server_default=''))
    op.add_column('clientes',
                  sa.Column('aceita_novidades', sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.create_index('ix_clientes_email', 'clientes', ['email'], unique=True)


def downgrade():
    op.drop_index('ix_clientes_email', table_name='clientes')
    op.drop_column('clientes', 'aceita_novidades')
    op.drop_column('clientes', 'senha_hash')
    op.drop_column('clientes', 'email')
