"""pecas.composicao e pecas.medidas (detalhes da roupa na vitrine)

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
"""
import sqlalchemy as sa
from alembic import op

revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pecas", sa.Column("composicao", sa.Text(), nullable=True, server_default=""))
    op.add_column("pecas", sa.Column("medidas", sa.Text(), nullable=True, server_default=""))


def downgrade():
    op.drop_column("pecas", "medidas")
    op.drop_column("pecas", "composicao")
