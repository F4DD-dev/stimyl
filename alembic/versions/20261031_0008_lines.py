"""Remember the last bot line so two replies in a row are not the same."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261031_0008"
down_revision: str | Sequence[str] | None = "20261031_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("line_cursor", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("last_line", sa.String(length=40), nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("last_line")
        batch.drop_column("line_cursor")
