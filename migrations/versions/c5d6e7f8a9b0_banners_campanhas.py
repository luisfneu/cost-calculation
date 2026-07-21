"""banners, campanhas e campanha_pecas — carrossel da home e campanhas com desconto

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
"""
import sqlalchemy as sa
from alembic import op

revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade():
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
    op.create_table(
        "campanhas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nome", sa.String(120), nullable=False),
        sa.Column("slug", sa.String(140), nullable=False, unique=True),
        sa.Column("subtitulo", sa.String(255), server_default=""),
        sa.Column("ativa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("inicio", sa.Date()),
        sa.Column("fim", sa.Date()),
        sa.Column("banner_hero", sa.String(255)),
        sa.Column("banner_landing", sa.String(255)),
        sa.Column("filtro_colecao", sa.String(120), server_default=""),
        sa.Column("filtro_tipo", sa.String(60), server_default=""),
        sa.Column("filtro_tags", sa.String(255), server_default=""),
        sa.Column("desconto_tipo", sa.String(12), nullable=False, server_default="percentual"),
        sa.Column("desconto_valor", sa.Float(), nullable=False, server_default="0"),
        sa.Column("criado_em", sa.DateTime()),
    )
    op.create_table(
        "campanha_pecas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campanha_id", sa.Integer(), sa.ForeignKey("campanhas.id"), nullable=False),
        sa.Column("peca_id", sa.Integer(), sa.ForeignKey("pecas.id"), nullable=False),
        sa.Column("incluir", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("campanha_id", "peca_id", name="uq_campanha_peca"),
    )


def downgrade():
    op.drop_table("campanha_pecas")
    op.drop_table("campanhas")
    op.drop_table("banners")
