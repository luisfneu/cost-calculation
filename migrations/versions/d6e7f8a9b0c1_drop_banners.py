"""remove a tabela banners — unificado em Campanha (banner = campanha sem desconto)

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
"""
import sqlalchemy as sa
from alembic import op

revision = "d6e7f8a9b0c1"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("banners")


def downgrade():
    op.create_table(
        "banners",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("titulo", sa.String(120), server_default=""),
        sa.Column("imagem", sa.String(255)),
        sa.Column("imagem_mobile", sa.String(255)),
        sa.Column("ordem", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("inicio", sa.Date()),
        sa.Column("fim", sa.Date()),
        sa.Column("destino_tipo", sa.String(12), nullable=False, server_default="url"),
        sa.Column("destino_valor", sa.String(255), server_default=""),
        sa.Column("criado_em", sa.DateTime()),
    )
