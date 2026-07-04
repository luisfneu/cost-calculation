"""peca vitrine_publica

Revision ID: 6fc4859b366b
Revises: 773a10bece6d
Create Date: 2026-07-03 19:38:53.823903

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6fc4859b366b'
down_revision = '773a10bece6d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pecas', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('vitrine_publica', sa.Boolean(), nullable=False, server_default=sa.text("1"))
        )


def downgrade():
    with op.batch_alter_table('pecas', schema=None) as batch_op:
        batch_op.drop_column('vitrine_publica')
