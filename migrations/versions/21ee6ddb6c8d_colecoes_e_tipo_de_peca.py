"""colecoes e tipo de peca

Revision ID: 21ee6ddb6c8d
Revises: 510cf3f0f0eb
Create Date: 2026-07-03 10:27:37.751262

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '21ee6ddb6c8d'
down_revision = '510cf3f0f0eb'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'colecoes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=False),
        sa.Column('slogan', sa.String(length=255), nullable=True),
        sa.Column('foto', sa.String(length=255), nullable=True),
        sa.Column('criado_em', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('nome'),
    )
    with op.batch_alter_table('pecas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tipo', sa.String(length=60), nullable=True))


def downgrade():
    with op.batch_alter_table('pecas', schema=None) as batch_op:
        batch_op.drop_column('tipo')
    op.drop_table('colecoes')
