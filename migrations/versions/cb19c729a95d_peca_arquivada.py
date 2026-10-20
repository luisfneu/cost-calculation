"""pecas: arquivada/arquivada_em — soft delete (sai das listas, nada é apagado)

Revision ID: cb19c729a95d
Revises: 35b5e766ad08
"""

import sqlalchemy as sa
from alembic import op

revision = "cb19c729a95d"
down_revision = "35b5e766ad08"
branch_labels = None
depends_on = None


def upgrade():
    # add_column direto (sem batch): a base tem FK legada que quebra o recreate.
    op.add_column("pecas", sa.Column("arquivada", sa.Boolean(), nullable=False,
                                     server_default="0"))
    op.add_column("pecas", sa.Column("arquivada_em", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("pecas", "arquivada_em")
    op.drop_column("pecas", "arquivada")
