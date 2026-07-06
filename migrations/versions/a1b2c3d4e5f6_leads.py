"""leads (pré-cadastro da vitrine)

Revision ID: a1b2c3d4e5f6
Revises: 6fc4859b366b
Create Date: 2026-07-04 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '6fc4859b366b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'leads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=160), nullable=False),
        sa.Column('instagram', sa.String(length=80)),
        sa.Column('telefone', sa.String(length=40)),
        sa.Column('cep', sa.String(length=12)),
        sa.Column('logradouro', sa.String(length=160)),
        sa.Column('numero', sa.String(length=20)),
        sa.Column('complemento', sa.String(length=80)),
        sa.Column('bairro', sa.String(length=80)),
        sa.Column('cidade', sa.String(length=80)),
        sa.Column('uf', sa.String(length=2)),
        sa.Column('observacao', sa.Text()),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pendente'),
        sa.Column('cliente_id', sa.Integer()),
        sa.Column('criado_em', sa.DateTime()),
        sa.Column('confirmado_em', sa.DateTime()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id']),
    )


def downgrade():
    op.drop_table('leads')
