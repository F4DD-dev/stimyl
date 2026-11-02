"""School directory and join applications. Old columns stay."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261101_0010"
down_revision: str | Sequence[str] | None = "20261031_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("region", sa.String(length=120), nullable=True))
    op.add_column("schools", sa.Column("city", sa.String(length=120), nullable=True))
    op.add_column("schools", sa.Column("external_key", sa.String(length=64), nullable=True))
    op.create_index("uq_schools_external_key", "schools", ["external_key"], unique=True)
    op.create_table(
        "join_applications",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("wanted_role", sa.String(length=16), nullable=False),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=True),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), nullable=True),
        sa.Column("seat_code", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "wanted_role IN ('student', 'teacher', 'admin')",
            name="ck_join_applications_role",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'pending', 'approved')",
            name="ck_join_applications_status",
        ),
    )
    op.create_table(
        "staff_seats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("school_id", sa.Integer(), sa.ForeignKey("schools.id"), nullable=False),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("class_id", "code", name="uq_staff_seats_class_code"),
    )


def downgrade() -> None:
    op.drop_table("staff_seats")
    op.drop_table("join_applications")
    op.drop_index("uq_schools_external_key", table_name="schools")
    op.drop_column("schools", "external_key")
    op.drop_column("schools", "city")
    op.drop_column("schools", "region")
