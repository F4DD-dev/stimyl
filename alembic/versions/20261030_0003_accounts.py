"""Accounts, schools and login sessions."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261030_0003"
down_revision: str | Sequence[str] | None = "20261027_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schools",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        sa.text(
            "INSERT INTO schools (title, created_at) "
            "VALUES ('Демо-школа', CURRENT_TIMESTAMP)"
        )
    )
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("status", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(sa.text("UPDATE users SET status = 'active' WHERE status IS NULL"))
    op.execute(sa.text("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
    op.create_table(
        "auth_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "external_id", name="uq_auth_provider_external"),
    )
    op.create_index("ix_auth_identities_user_id", "auth_identities", ["user_id"])
    op.execute(
        sa.text(
            "INSERT INTO auth_identities (user_id, provider, external_id, created_at) "
            "SELECT id, 'max', max_user_id, CURRENT_TIMESTAMP FROM users"
        )
    )
    op.create_table(
        "consents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_consents_user_id", "consents", ["user_id"])
    op.execute(
        sa.text(
            "INSERT INTO consents (user_id, policy_version, accepted_at) "
            "SELECT id, '2026-10-30', CURRENT_TIMESTAMP FROM users"
        )
    )
    op.create_table(
        "web_login_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code_hash", name="uq_web_login_codes_hash"),
    )
    op.create_index("ix_web_login_codes_user_id", "web_login_codes", ["user_id"])
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_agent", sa.String(length=200), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_table(
        "teacher_applications",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("full_name", sa.String(length=200), nullable=True),
        sa.Column("school_name", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'pending', 'approved', 'rejected')",
            name="ck_teacher_applications_status",
        ),
    )
    op.create_table(
        "teacher_invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code_hash", name="uq_teacher_invites_hash"),
    )
    op.create_table(
        "transfer_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code_hash", name="uq_transfer_codes_hash"),
    )
    op.create_index("ix_transfer_codes_user_id", "transfer_codes", ["user_id"])
    op.create_table(
        "signup_hints",
        sa.Column("external_id", sa.String(length=64), primary_key=True),
        sa.Column("start_payload", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "login_guards",
        sa.Column("ip", sa.String(length=64), primary_key=True),
        sa.Column("failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table("classes") as batch:
        batch.add_column(sa.Column("school_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("join_key", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("join_code", sa.String(length=16), nullable=True))
        batch.add_column(
            sa.Column("timezone", sa.String(length=64), nullable=True, server_default="Europe/Moscow")
        )
    _backfill_classes()
    with op.batch_alter_table("users") as batch:
        batch.alter_column("status", existing_type=sa.String(length=16), nullable=False)
        batch.alter_column("created_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.drop_constraint("ck_users_role", type_="check")
        batch.create_check_constraint(
            "ck_users_role", "role IN ('student', 'teacher', 'admin')"
        )
        batch.create_check_constraint(
            "ck_users_status", "status IN ('pending', 'active', 'blocked')"
        )
        batch.drop_column("max_user_id")
    with op.batch_alter_table("classes") as batch:
        batch.alter_column("school_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("join_key", existing_type=sa.String(length=128), nullable=False)
        batch.alter_column("join_code", existing_type=sa.String(length=16), nullable=False)
        batch.alter_column("timezone", existing_type=sa.String(length=64), nullable=False)
        batch.create_foreign_key("fk_classes_school_id", "schools", ["school_id"], ["id"])
        batch.drop_constraint("uq_classes_title", type_="unique")
        batch.create_unique_constraint("uq_classes_school_title", ["school_id", "title"])
        batch.create_unique_constraint("uq_classes_join_key", ["join_key"])
        batch.create_unique_constraint("uq_classes_join_code", ["join_code"])


def _backfill_classes() -> None:
    conn = op.get_bind()
    school_id = conn.execute(sa.text("SELECT id FROM schools ORDER BY id LIMIT 1")).scalar()
    rows = conn.execute(sa.text("SELECT id, title FROM classes")).all()
    for class_id, title in rows:
        if title == "8Б":
            join_key, join_code = "8b-demo", "8BDEMO"
        else:
            join_key, join_code = f"c{class_id}", f"K{int(class_id):05d}"
        conn.execute(
            sa.text(
                "UPDATE classes SET school_id = :school_id, join_key = :join_key, "
                "join_code = :join_code, timezone = 'Europe/Moscow' WHERE id = :class_id"
            ),
            {
                "school_id": school_id,
                "join_key": join_key,
                "join_code": join_code,
                "class_id": class_id,
            },
        )


def downgrade() -> None:
    with op.batch_alter_table("classes") as batch:
        batch.drop_constraint("uq_classes_join_code", type_="unique")
        batch.drop_constraint("uq_classes_join_key", type_="unique")
        batch.drop_constraint("uq_classes_school_title", type_="unique")
        batch.drop_constraint("fk_classes_school_id", type_="foreignkey")
        batch.create_unique_constraint("uq_classes_title", ["title"])
        batch.drop_column("timezone")
        batch.drop_column("join_code")
        batch.drop_column("join_key")
        batch.drop_column("school_id")
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("max_user_id", sa.String(length=64), nullable=True))
    op.execute(
        sa.text(
            "UPDATE users SET max_user_id = ("
            "SELECT external_id FROM auth_identities "
            "WHERE auth_identities.user_id = users.id AND auth_identities.provider = 'max'"
            ")"
        )
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            sa.text("UPDATE users SET max_user_id = 'missing-' || id WHERE max_user_id IS NULL")
        )
    else:
        op.execute(
            sa.text(
                "UPDATE users SET max_user_id = 'missing-' || id::text WHERE max_user_id IS NULL"
            )
        )
    with op.batch_alter_table("users") as batch:
        batch.alter_column("max_user_id", existing_type=sa.String(length=64), nullable=False)
        batch.create_unique_constraint("uq_users_max_user_id", ["max_user_id"])
        batch.drop_constraint("ck_users_status", type_="check")
        batch.drop_constraint("ck_users_role", type_="check")
        batch.create_check_constraint("ck_users_role", "role IN ('student', 'teacher')")
        batch.drop_column("deleted_at")
        batch.drop_column("last_seen_at")
        batch.drop_column("created_at")
        batch.drop_column("status")
    op.drop_table("login_guards")
    op.drop_table("signup_hints")
    op.drop_index("ix_transfer_codes_user_id", table_name="transfer_codes")
    op.drop_table("transfer_codes")
    op.drop_table("teacher_invites")
    op.drop_table("teacher_applications")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_index("ix_web_login_codes_user_id", table_name="web_login_codes")
    op.drop_table("web_login_codes")
    op.drop_index("ix_consents_user_id", table_name="consents")
    op.drop_table("consents")
    op.drop_index("ix_auth_identities_user_id", table_name="auth_identities")
    op.drop_table("auth_identities")
    op.drop_table("schools")
