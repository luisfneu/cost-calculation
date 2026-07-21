"""newsletter_envios — histórico de e-mails de newsletter enviados

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
"""
import sqlalchemy as sa
from alembic import op

revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "newsletter_envios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assunto", sa.String(200), nullable=False, server_default=""),
        sa.Column("html", sa.Text(), nullable=False, server_default=""),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("criado_em", sa.DateTime()),
    )


def downgrade():
    op.drop_table("newsletter_envios")
