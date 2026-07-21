"""newsletter_inscritos — e-mails avulsos captados no rodapé da loja

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
"""
import sqlalchemy as sa
from alembic import op

revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "newsletter_inscritos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(160), nullable=False, unique=True),
        sa.Column("nome", sa.String(160), server_default=""),
        sa.Column("cliente_id", sa.Integer(), sa.ForeignKey("clientes.id")),
        sa.Column("criado_em", sa.DateTime()),
    )


def downgrade():
    op.drop_table("newsletter_inscritos")
