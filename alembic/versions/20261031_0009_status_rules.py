"""Hint credit on an attempt, and the started status before three tries."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261031_0009"
down_revision: str | Sequence[str] | None = "20261031_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("attempts") as batch:
        batch.add_column(
            sa.Column("hinted", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.drop_constraint("ck_topic_states_status", "topic_states", type_="check")
    op.create_check_constraint(
        "ck_topic_states_status",
        "topic_states",
        "status IN ('started', 'mastered', 'needs_practice', 'repeat')",
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM topic_states WHERE status = 'started'"))
    op.drop_constraint("ck_topic_states_status", "topic_states", type_="check")
    op.create_check_constraint(
        "ck_topic_states_status",
        "topic_states",
        "status IN ('mastered', 'needs_practice', 'repeat')",
    )
    with op.batch_alter_table("attempts") as batch:
        batch.drop_column("hinted")
