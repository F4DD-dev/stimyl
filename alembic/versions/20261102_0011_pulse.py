"""Phone verification, school management, works and notices."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261102_0011"
down_revision: str | Sequence[str] | None = "20261101_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("can_manage_school", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("users", sa.Column("phone_hash", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("phone_mask", sa.String(length=32), nullable=True))
    op.add_column(
        "users",
        sa.Column("test_signup", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index("uq_users_phone_hash", "users", ["phone_hash"], unique=True)
    op.drop_constraint("ck_join_applications_status", "join_applications", type_="check")
    op.create_check_constraint(
        "ck_join_applications_status",
        "join_applications",
        "status IN ('draft', 'pending', 'approved', 'rejected')",
    )
    op.add_column("join_applications", sa.Column("reviewed_by", sa.Integer(), nullable=True))
    op.add_column(
        "join_applications",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_join_applications_reviewed_by",
        "join_applications",
        "users",
        ["reviewed_by"],
        ["id"],
    )
    op.create_table(
        "class_subject_teachers",
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), primary_key=True),
    )
    op.create_table(
        "works",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("goal", sa.String(length=300), nullable=False),
        sa.Column("difficulty", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("audience", sa.String(length=16), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('draft', 'published')", name="ck_works_status"),
        sa.CheckConstraint("difficulty IN ('easy', 'normal', 'hard')", name="ck_works_difficulty"),
        sa.CheckConstraint("audience IN ('class', 'selected')", name="ck_works_audience"),
    )
    op.create_table(
        "work_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_id", sa.Integer(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.String(length=500), nullable=False),
        sa.Column("expected", sa.String(length=64), nullable=False),
    )
    op.create_table(
        "work_recipients",
        sa.Column("work_id", sa.Integer(), sa.ForeignKey("works.id"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="assigned"),
        sa.CheckConstraint(
            "status IN ('draft', 'assigned', 'done')",
            name="ck_work_recipients_status",
        ),
    )
    op.create_table(
        "work_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_id", sa.Integer(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("work_items.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("answer", sa.String(length=200), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("item_id", "user_id", name="uq_work_answers_item_user"),
    )
    op.create_table(
        "notices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_notices_user_id", "notices", ["user_id"])
    op.create_table(
        "outbound_notices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=500), nullable=False),
        sa.Column("button_text", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("button_payload", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("ref_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="ck_outbound_notices_status",
        ),
    )
    op.create_index("ix_outbound_notices_user_id", "outbound_notices", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_outbound_notices_user_id", table_name="outbound_notices")
    op.drop_table("outbound_notices")
    op.drop_index("ix_notices_user_id", table_name="notices")
    op.drop_table("notices")
    op.drop_table("work_answers")
    op.drop_table("work_recipients")
    op.drop_table("work_items")
    op.drop_table("works")
    op.drop_table("class_subject_teachers")
    op.drop_constraint("fk_join_applications_reviewed_by", "join_applications", type_="foreignkey")
    op.drop_column("join_applications", "reviewed_at")
    op.drop_column("join_applications", "reviewed_by")
    op.drop_constraint("ck_join_applications_status", "join_applications", type_="check")
    op.create_check_constraint(
        "ck_join_applications_status",
        "join_applications",
        "status IN ('draft', 'pending', 'approved')",
    )
    op.drop_index("uq_users_phone_hash", table_name="users")
    op.drop_column("users", "test_signup")
    op.drop_column("users", "phone_mask")
    op.drop_column("users", "phone_hash")
    op.drop_column("users", "can_manage_school")
