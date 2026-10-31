"""Hint ladder fields on the learning session."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261031_0006"
down_revision: str | Sequence[str] | None = "20261031_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("hint_step", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("task_misses", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("pending_step", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("pending_text", sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("pending_text")
        batch.drop_column("pending_step")
        batch.drop_column("task_misses")
        batch.drop_column("hint_step")
