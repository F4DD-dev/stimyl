"""Teacher-written note on a topic."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261103_0013"
down_revision: str | Sequence[str] | None = "20261103_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "topics",
        sa.Column("blurb", sa.String(length=800), server_default="", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("topics", "blurb")
