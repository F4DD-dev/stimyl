"""Practice level and streaks on the learning session."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261031_0005"
down_revision: str | Sequence[str] | None = "20261030_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(
            sa.Column("level", sa.String(length=8), nullable=False, server_default="easy")
        )
        batch.add_column(
            sa.Column("correct_streak", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("wrong_streak", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("wrong_streak")
        batch.drop_column("correct_streak")
        batch.drop_column("level")
