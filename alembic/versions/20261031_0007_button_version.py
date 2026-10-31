"""Version of the dialog step, stored on button payloads."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261031_0007"
down_revision: str | Sequence[str] | None = "20261031_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(
            sa.Column("state_version", sa.Integer(), nullable=False, server_default="1")
        )


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("state_version")
