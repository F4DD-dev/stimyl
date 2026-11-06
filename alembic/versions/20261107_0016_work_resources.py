"""Resources attached to a work: downloadable files and external links."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261107_0016"
down_revision: str | Sequence[str] | None = "20261106_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_id", sa.Integer(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("url", sa.String(length=1000), nullable=True),
        sa.Column("mime", sa.String(length=100), nullable=False),
        sa.Column("blob", sa.LargeBinary(), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('file', 'link')", name="ck_work_resources_kind"),
    )
    op.create_index("ix_work_resources_work_id", "work_resources", ["work_id"])


def downgrade() -> None:
    op.drop_index("ix_work_resources_work_id", table_name="work_resources")
    op.drop_table("work_resources")
