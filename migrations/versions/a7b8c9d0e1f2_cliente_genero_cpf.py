"""clientes.genero e clientes.cpf

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-10
"""
import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clientes", sa.Column("genero", sa.String(length=20), server_default=""))
    op.add_column("clientes", sa.Column("cpf", sa.String(length=14), server_default=""))


def downgrade():
    op.drop_column("clientes", "cpf")
    op.drop_column("clientes", "genero")
