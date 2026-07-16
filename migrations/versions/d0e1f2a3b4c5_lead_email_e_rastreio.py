"""leads.email (checkout convidado) + vendas.rastreio (código de rastreio)

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-11

- leads.email: e-mail opcional do convidado no checkout — melhora o casamento
  com a conta futura (antes só WhatsApp, via reivindicação frágil).
- vendas.rastreio: código de rastreio do envio, exibido no stepper do cliente.
IMPORTANTE: op.add_column direto (sem batch) — padrão do projeto (FK legada).
"""
import sqlalchemy as sa
from alembic import op

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("leads",
                  sa.Column("email", sa.String(length=160), nullable=False, server_default=""))
    op.add_column("vendas",
                  sa.Column("rastreio", sa.String(length=60), nullable=False, server_default=""))


def downgrade():
    op.drop_column("vendas", "rastreio")
    op.drop_column("leads", "email")
