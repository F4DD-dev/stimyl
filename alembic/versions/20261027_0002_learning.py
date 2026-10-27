"""Training sessions, attempts and topic status."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261027_0002"
down_revision: str | Sequence[str] | None = "20261027_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=True),
        sa.Column("step", sa.String(length=16), nullable=False),
        sa.Column("example_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("task_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_answer", sa.String(length=64), nullable=True),
        sa.Column("pending_hint", sa.String(length=500), nullable=True),
        sa.Column("pending_prompt", sa.String(length=500), nullable=True),
        sa.Column("photo_token", sa.String(length=512), nullable=True),
        sa.Column("photo_url", sa.String(length=1000), nullable=True),
        sa.Column("photo_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('training', 'submission')", name="ck_sessions_mode"),
        sa.CheckConstraint(
            "step IN ('explain', 'practice', 'check', 'done')",
            name="ck_sessions_step",
        ),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("text", sa.String(length=4000), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('student', 'bot')", name="ck_messages_role"),
        sa.CheckConstraint(
            "visibility IN ('private', 'submission')",
            name="ck_messages_visibility",
        ),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])
    op.create_table(
        "attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id"), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("prompt", sa.String(length=500), nullable=False),
        sa.Column("expected", sa.String(length=64), nullable=False),
        sa.Column("answer", sa.String(length=200), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("feedback", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('training', 'submission')", name="ck_attempts_mode"),
    )
    op.create_index("ix_attempts_user_topic", "attempts", ["user_id", "topic_id"])
    op.create_table(
        "topic_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("correct_ratio", sa.Float(), nullable=False),
        sa.Column("attempts_count", sa.Integer(), nullable=False),
        sa.Column("has_recheck", sa.Boolean(), nullable=False),
        sa.Column("last_attempt_on", sa.Date(), nullable=False),
        sa.CheckConstraint(
            "status IN ('mastered', 'needs_practice', 'repeat')",
            name="ck_topic_states_status",
        ),
        sa.UniqueConstraint("user_id", "topic_id", name="uq_topic_states_user_topic"),
    )
    op.create_index("ix_topic_states_user_id", "topic_states", ["user_id"])
    op.create_table(
        "inbound_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dedup_key", sa.String(length=200), nullable=False),
        sa.UniqueConstraint("dedup_key", name="uq_inbound_events_dedup_key"),
    )
    op.create_table(
        "runtime_flags",
        sa.Column("key", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.String(length=256), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("runtime_flags")
    op.drop_table("inbound_events")
    op.drop_index("ix_topic_states_user_id", table_name="topic_states")
    op.drop_table("topic_states")
    op.drop_index("ix_attempts_user_topic", table_name="attempts")
    op.drop_table("attempts")
    op.drop_index("ix_messages_session_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
