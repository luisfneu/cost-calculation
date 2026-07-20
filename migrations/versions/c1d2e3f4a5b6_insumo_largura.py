"""insumos: largura_cm do tecido (informativo)

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
"""
import sqlalchemy as sa
from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("insumos", sa.Column("largura_cm", sa.Float(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("insumos", "largura_cm")
