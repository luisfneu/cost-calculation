"""insumos: composicao (tecido) + migra tipo materia_prima -> aviamento

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
"""
import sqlalchemy as sa
from alembic import op

revision = "b0c1d2e3f4a5"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("insumos", sa.Column("composicao", sa.Text(), server_default=""))
    # "Matéria-prima" foi dividida em Tecido/Aviamento; o legado vira aviamento
    # (catch-all). O usuário reclassifica os tecidos manualmente.
    op.execute("UPDATE insumos SET tipo='aviamento' WHERE tipo='materia_prima'")


def downgrade():
    op.execute("UPDATE insumos SET tipo='materia_prima' WHERE tipo IN ('tecido','aviamento')")
    op.drop_column("insumos", "composicao")
