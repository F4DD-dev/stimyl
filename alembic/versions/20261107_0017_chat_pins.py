"""Pinned flag for assistant chats."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261107_0017"
down_revision: str | Sequence[str] | None = "20261107_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assistant_chats",
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("assistant_chats", "pinned")
