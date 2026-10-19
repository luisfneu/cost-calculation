"""vendas/pagamentos: campos para pagamento online com cartão (Mercado Pago)

Revision ID: a1b2c3d4e5f6
Revises: d2e3f4a5b6c7
"""

import sqlalchemy as sa
from alembic import op

revision = "35b5e766ad08"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade():
    # add_column direto (sem batch): a base tem FK legada que quebra o recreate.
    op.add_column("vendas", sa.Column("mp_preference_id", sa.String(length=80),
                                      nullable=False, server_default=""))
    op.add_column("vendas", sa.Column("mp_payment_id", sa.String(length=40),
                                      nullable=False, server_default=""))
    op.add_column("pagamentos", sa.Column("externo_id", sa.String(length=60),
                                          nullable=False, server_default=""))


def downgrade():
    op.drop_column("pagamentos", "externo_id")
    op.drop_column("vendas", "mp_payment_id")
    op.drop_column("vendas", "mp_preference_id")
