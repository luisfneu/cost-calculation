"""insumos: frete_compra e frete_qtd — frete da compra rateado no custo

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""

import sqlalchemy as sa
from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade():
    # add_column direto (sem batch): a base tem FK legada que quebra o recreate.
    op.add_column("insumos", sa.Column("frete_compra", sa.Float(), nullable=False,
                                       server_default="0"))
    op.add_column("insumos", sa.Column("frete_qtd", sa.Float(), nullable=False,
                                       server_default="0"))


def downgrade():
    op.drop_column("insumos", "frete_qtd")
    op.drop_column("insumos", "frete_compra")
