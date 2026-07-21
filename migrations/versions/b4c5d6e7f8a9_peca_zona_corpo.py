"""pecas.zona_corpo — zona que a peça veste (superior/inferior/inteiro), guia o provador

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
"""
import sqlalchemy as sa
from alembic import op

revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("pecas", sa.Column("zona_corpo", sa.String(10), nullable=True,
                                     server_default="inteiro"))


def downgrade():
    op.drop_column("pecas", "zona_corpo")
