"""Assistant chats and messages, stored per user."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261106_0015"
down_revision: str | Sequence[str] | None = "20261105_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_chats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('student', 'teacher')", name="ck_assistant_chats_kind"),
    )
    op.create_index("ix_assistant_chats_user_id", "assistant_chats", ["user_id"])
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "chat_id",
            sa.Integer(),
            sa.ForeignKey("assistant_chats.id"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="text"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')", name="ck_assistant_messages_role"
        ),
    )
    op.create_index("ix_assistant_messages_chat_id", "assistant_messages", ["chat_id"])
    op.create_index("ix_assistant_messages_user_id", "assistant_messages", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_assistant_messages_user_id", table_name="assistant_messages")
    op.drop_index("ix_assistant_messages_chat_id", table_name="assistant_messages")
    op.drop_table("assistant_messages")
    op.drop_index("ix_assistant_chats_user_id", table_name="assistant_chats")
    op.drop_table("assistant_chats")
