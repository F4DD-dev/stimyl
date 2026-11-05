"""Lesson materials and their fragments."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261105_0014"
down_revision: str | Sequence[str] | None = "20261103_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "materials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("chars", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_materials_class_id", "materials", ["class_id"])
    op.create_table(
        "material_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "material_id",
            sa.Integer(),
            sa.ForeignKey("materials.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("ix_material_chunks_material_id", "material_chunks", ["material_id"])
    op.create_index("ix_material_chunks_class_id", "material_chunks", ["class_id"])
    op.execute(
        "CREATE INDEX ix_material_chunks_fts ON material_chunks "
        "USING gin (to_tsvector('russian', text))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_material_chunks_fts")
    op.drop_index("ix_material_chunks_class_id", table_name="material_chunks")
    op.drop_index("ix_material_chunks_material_id", table_name="material_chunks")
    op.drop_table("material_chunks")
    op.drop_index("ix_materials_class_id", table_name="materials")
    op.drop_table("materials")
