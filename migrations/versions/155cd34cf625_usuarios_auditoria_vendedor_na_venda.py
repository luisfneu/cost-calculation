"""usuarios, auditoria, vendedor na venda

Revision ID: 155cd34cf625
Revises: 08ab5ddc7a6a
Create Date: 2026-07-02 18:21:01.431801

Migração enxuta: cria as tabelas de usuários e auditoria e adiciona a coluna
'vendedor' em vendas. Os alter_column de NOT NULL que o autogenerate sugeriu
foram removidos de propósito (são só divergências cosméticas do schema antigo e
recriariam tabelas no SQLite sem necessidade).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '155cd34cf625'
down_revision = '08ab5ddc7a6a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'auditoria',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario', sa.String(length=80), nullable=True),
        sa.Column('acao', sa.String(length=40), nullable=False),
        sa.Column('detalhe', sa.String(length=255), nullable=True),
        sa.Column('criado_em', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'usuarios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome', sa.String(length=120), nullable=False),
        sa.Column('login', sa.String(length=60), nullable=False),
        sa.Column('senha_hash', sa.String(length=255), nullable=False),
        sa.Column('ativo', sa.Boolean(), nullable=False),
        sa.Column('admin', sa.Boolean(), nullable=False),
        sa.Column('criado_em', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('login'),
    )
    with op.batch_alter_table('vendas', schema=None) as batch_op:
        batch_op.add_column(sa.Column('vendedor', sa.String(length=80), nullable=True))


def downgrade():
    with op.batch_alter_table('vendas', schema=None) as batch_op:
        batch_op.drop_column('vendedor')
    op.drop_table('usuarios')
    op.drop_table('auditoria')
