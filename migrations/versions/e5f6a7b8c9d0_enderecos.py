"""enderecos — múltiplos endereços por cliente, com um principal

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-10

Cria a tabela `enderecos` e migra o endereço atual de cada cliente (campos em
`clientes`) para um registro principal. Os campos de endereço em `clientes`
continuam existindo e são mantidos em sincronia com o endereço principal
(checkout/preferências ainda os usam).
"""
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "enderecos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cliente_id", sa.Integer(), sa.ForeignKey("clientes.id"), nullable=False),
        sa.Column("apelido", sa.String(length=60), server_default=""),
        sa.Column("destinatario", sa.String(length=160), server_default=""),
        sa.Column("cep", sa.String(length=12), server_default=""),
        sa.Column("logradouro", sa.String(length=160), server_default=""),
        sa.Column("numero", sa.String(length=20), server_default=""),
        sa.Column("complemento", sa.String(length=80), server_default=""),
        sa.Column("bairro", sa.String(length=80), server_default=""),
        sa.Column("cidade", sa.String(length=80), server_default=""),
        sa.Column("uf", sa.String(length=2), server_default=""),
        sa.Column("principal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("criado_em", sa.DateTime()),
    )
    # Backfill: cada cliente com endereço vira 1 endereço principal.
    op.get_bind().execute(sa.text("""
        INSERT INTO enderecos (cliente_id, destinatario, cep, logradouro, numero,
                               complemento, bairro, cidade, uf, principal, criado_em)
        SELECT id, nome, COALESCE(cep,''), COALESCE(logradouro,''), COALESCE(numero,''),
               COALESCE(complemento,''), COALESCE(bairro,''), COALESCE(cidade,''),
               COALESCE(uf,''), 1, :agora
        FROM clientes
        WHERE COALESCE(logradouro,'') != '' OR COALESCE(cep,'') != ''
    """), {"agora": datetime.utcnow()})


def downgrade():
    op.drop_table("enderecos")
