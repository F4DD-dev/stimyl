"""Jobs queue, login tickets and class approval."""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261030_0004"
down_revision: str | Sequence[str] | None = "20261030_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dedup_key", sa.String(length=200), nullable=False),
        sa.Column("user_key", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'done', 'dead')",
            name="ck_jobs_status",
        ),
        sa.UniqueConstraint("dedup_key", name="uq_jobs_dedup_key"),
    )
    op.create_index("ix_jobs_status_run_at", "jobs", ["status", "run_at"])
    with op.batch_alter_table("enrollments") as batch:
        batch.add_column(sa.Column("status", sa.String(length=16), nullable=True))
    op.execute(sa.text("UPDATE enrollments SET status = 'active' WHERE status IS NULL"))
    with op.batch_alter_table("enrollments") as batch:
        batch.alter_column("status", existing_type=sa.String(length=16), nullable=False)
        batch.create_check_constraint(
            "ck_enrollments_status", "status IN ('pending', 'active')"
        )
    with op.batch_alter_table("classes") as batch:
        batch.add_column(sa.Column("join_open", sa.Boolean(), nullable=True, server_default=sa.true()))
    op.execute(sa.text("UPDATE classes SET join_open = true WHERE join_open IS NULL"))
    _drop_demo_keys()
    with op.batch_alter_table("classes") as batch:
        batch.alter_column("join_open", existing_type=sa.Boolean(), nullable=False)
    with op.batch_alter_table("user_sessions") as batch:
        batch.add_column(sa.Column("csrf_token", sa.String(length=64), nullable=True))
    op.execute(sa.text("UPDATE user_sessions SET csrf_token = 'legacy' WHERE csrf_token IS NULL"))
    with op.batch_alter_table("user_sessions") as batch:
        batch.alter_column("csrf_token", existing_type=sa.String(length=64), nullable=False)
    with op.batch_alter_table("web_login_codes") as batch:
        batch.add_column(sa.Column("token_hash", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("public_id", sa.String(length=16), nullable=True))
    op.create_index("uq_web_login_token", "web_login_codes", ["token_hash"], unique=True)
    op.create_index("uq_web_login_public", "web_login_codes", ["public_id"], unique=True)
    with op.batch_alter_table("teacher_invites") as batch:
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=True, server_default="0"))
    with op.batch_alter_table("transfer_codes") as batch:
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=True, server_default="0"))
    op.execute(sa.text("UPDATE teacher_invites SET attempts = 0 WHERE attempts IS NULL"))
    op.execute(sa.text("UPDATE transfer_codes SET attempts = 0 WHERE attempts IS NULL"))


def _drop_demo_keys() -> None:
    """Ключи 8b-demo и 8BDEMO не оставляем в уже существующем классе."""
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id FROM classes WHERE join_key = '8b-demo' OR join_code = '8BDEMO'")
    ).all()
    for (class_id,) in rows:
        conn.execute(
            sa.text(
                "UPDATE classes SET join_key = :join_key, join_code = :join_code WHERE id = :class_id"
            ),
            {
                "join_key": "k-" + secrets.token_hex(8),
                "join_code": secrets.token_hex(4).upper(),
                "class_id": class_id,
            },
        )


def downgrade() -> None:
    with op.batch_alter_table("transfer_codes") as batch:
        batch.drop_column("attempts")
    with op.batch_alter_table("teacher_invites") as batch:
        batch.drop_column("attempts")
    op.drop_index("uq_web_login_public", table_name="web_login_codes")
    op.drop_index("uq_web_login_token", table_name="web_login_codes")
    with op.batch_alter_table("web_login_codes") as batch:
        batch.drop_column("public_id")
        batch.drop_column("token_hash")
    with op.batch_alter_table("user_sessions") as batch:
        batch.drop_column("csrf_token")
    with op.batch_alter_table("classes") as batch:
        batch.drop_column("join_open")
    with op.batch_alter_table("enrollments") as batch:
        batch.drop_constraint("ck_enrollments_status", type_="check")
        batch.drop_column("status")
    op.drop_index("ix_jobs_status_run_at", table_name="jobs")
    op.drop_table("jobs")
