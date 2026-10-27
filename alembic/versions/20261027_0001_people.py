"""People, class, subject and topics."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261027_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("max_user_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.CheckConstraint("role IN ('student', 'teacher')", name="ck_users_role"),
        sa.UniqueConstraint("max_user_id", name="uq_users_max_user_id"),
    )
    op.create_table(
        "classes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("title", name="uq_classes_title"),
    )
    op.create_table(
        "class_teachers",
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
    )
    op.create_table(
        "enrollments",
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
    )
    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.UniqueConstraint("title", name="uq_subjects_title"),
    )
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("subject_id", "position", name="uq_topics_subject_position"),
        sa.UniqueConstraint("subject_id", "title", name="uq_topics_subject_title"),
    )
    op.create_index("ix_topics_subject_id", "topics", ["subject_id"])


def downgrade() -> None:
    op.drop_index("ix_topics_subject_id", table_name="topics")
    op.drop_table("topics")
    op.drop_table("subjects")
    op.drop_table("enrollments")
    op.drop_table("class_teachers")
    op.drop_table("classes")
    op.drop_table("users")
