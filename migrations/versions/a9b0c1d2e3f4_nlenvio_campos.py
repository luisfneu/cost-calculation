"""newsletter_envios: campos originais do form (corpo, campanha, CTA) p/ reaproveitar

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
"""
import sqlalchemy as sa
from alembic import op

revision = "a9b0c1d2e3f4"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("newsletter_envios", sa.Column("corpo", sa.Text(), server_default=""))
    op.add_column("newsletter_envios", sa.Column("campanha_id", sa.Integer()))
    op.add_column("newsletter_envios", sa.Column("cta_texto", sa.String(120), server_default=""))
    op.add_column("newsletter_envios", sa.Column("cta_link", sa.String(255), server_default=""))


def downgrade():
    op.drop_column("newsletter_envios", "cta_link")
    op.drop_column("newsletter_envios", "cta_texto")
    op.drop_column("newsletter_envios", "campanha_id")
    op.drop_column("newsletter_envios", "corpo")
