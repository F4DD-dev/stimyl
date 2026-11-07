"""Class group chats in MAX."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261107_0018"
down_revision: str | Sequence[str] | None = "20261107_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "class_chats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("class_id", sa.Integer(), sa.ForeignKey("classes.id"), nullable=True),
        sa.Column("max_chat_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("ai_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("max_chat_id", name="uq_class_chats_max_chat"),
    )
    op.create_index("ix_class_chats_class_id", "class_chats", ["class_id"])


def downgrade() -> None:
    op.drop_index("ix_class_chats_class_id", table_name="class_chats")
    op.drop_table("class_chats")
