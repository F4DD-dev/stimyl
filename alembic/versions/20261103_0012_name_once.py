"""One self-service rename per person."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261103_0012"
down_revision: str | Sequence[str] | None = "20261102_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("name_changed", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "name_changed")
