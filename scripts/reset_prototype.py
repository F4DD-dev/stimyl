"""Сброс пользовательских данных прототипа. По умолчанию только показывает план.

Удаление возможно только вместе:
- аргумент --yes
- STIMUL_ALLOW_RESET=1
- STIMUL_RESET_DATABASE совпадает с именем базы в DATABASE_URL
- ENV не prod

Схему, alembic_version, школы, классы, предметы и темы скрипт не удаляет.
Назначения в staff_seats снимаются, сами места остаются.
Флаг prototype_bootstrap после удаления становится open.
На общую или боевую базу его не запускать.
"""

import asyncio
import os
import sys
from urllib.parse import urlparse

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import make_engine

# Строки людей и их следы. Школы, классы, предметы и темы сюда не входят.
USER_TABLES = (
    "work_answers",
    "work_recipients",
    "work_items",
    "works",
    "notices",
    "outbound_notices",
    "jobs",
    "messages",
    "attempts",
    "topic_states",
    "sessions",
    "web_login_codes",
    "user_sessions",
    "consents",
    "auth_identities",
    "teacher_applications",
    "teacher_invites",
    "transfer_codes",
    "signup_hints",
    "login_guards",
    "audit_log",
    "inbound_events",
    "enrollments",
    "class_subject_teachers",
    "class_teachers",
    "join_applications",
    "users",
)

# Остаются. staff_seats чистится от user_id, но строки мест не удаляются.
KEPT_TABLES = (
    "runtime_flags",
    "staff_seats",
    "topics",
    "subjects",
    "classes",
    "schools",
)

TABLES = USER_TABLES + KEPT_TABLES


def database_name(url: str) -> str:
    parsed = urlparse(url.replace("+asyncpg", "", 1).replace("+psycopg", "", 1))
    return parsed.path.lstrip("/").split("?", 1)[0]


async def counts(connection) -> list[tuple[str, int]]:
    rows = []
    for table in TABLES:
        found = await connection.scalar(text("SELECT to_regclass(:name)"), {"name": f"public.{table}"})
        if found is None:
            rows.append((table, -1))
            continue
        value = await connection.scalar(text(f"SELECT count(*) FROM {table}"))
        rows.append((table, int(value or 0)))
    return rows


async def run(delete: bool) -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL пустой. Ничего не удалено.")
        return 1
    name = database_name(settings.database_url)
    print(f"База: {name}")
    print(f"ENV: {settings.env}")
    if delete:
        if settings.env == "prod":
            print("ENV=prod. Удаление запрещено.")
            return 2
        if os.environ.get("STIMUL_ALLOW_RESET") != "1":
            print("Нет STIMUL_ALLOW_RESET=1. Удаление запрещено.")
            return 2
        expected = os.environ.get("STIMUL_RESET_DATABASE", "")
        if not expected or expected != name:
            print("STIMUL_RESET_DATABASE не совпадает с именем базы. Удаление запрещено.")
            return 2
        if name in {"postgres", "template0", "template1"} or "prod" in name.casefold():
            print("Имя базы не похоже на отдельный тестовый контур. Удаление запрещено.")
            return 2
    print("Будут затронуты только строки, не структура:")
    engine = make_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            tallies = await counts(connection)
        for table, count in tallies:
            label = "нет таблицы" if count < 0 else str(count)
            print(f"  {table}: {label}")
        if not delete:
            print("Режим просмотра. Чтобы удалить строки, нужны --yes, STIMUL_ALLOW_RESET=1 и STIMUL_RESET_DATABASE.")
            return 0
        present = {table for table, count in tallies if count >= 0}
        targets = [table for table in USER_TABLES if table in present]
        if not targets:
            print("Пользовательских таблиц нет. Ничего не удалено.")
            return 1
        async with engine.begin() as connection:
            if "staff_seats" in present:
                await connection.execute(text("UPDATE staff_seats SET user_id = NULL"))
            for table in targets:
                await connection.execute(text(f"DELETE FROM {table}"))
                sequence = await connection.scalar(
                    text(
                        "SELECT pg_get_serial_sequence(format('%I.%I', n.nspname, c.relname), a.attname) "
                        "FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "JOIN pg_attribute a ON a.attrelid = c.oid "
                        "AND a.attname = 'id' AND NOT a.attisdropped "
                        "WHERE n.nspname = 'public' AND c.relname = :table"
                    ),
                    {"table": table},
                )
                if sequence:
                    await connection.execute(
                        text("SELECT setval(pg_get_serial_sequence(:table, 'id'), 1, false)"),
                        {"table": f"public.{table}"},
                    )
            if "runtime_flags" in present:
                await connection.execute(
                    text(
                        "INSERT INTO runtime_flags (key, value) VALUES ('prototype_bootstrap', 'open') "
                        "ON CONFLICT (key) DO UPDATE SET value = 'open'"
                    )
                )
        print("Пользовательские строки удалены. Класс, предмет, темы и alembic_version на месте.")
        print("prototype_bootstrap = open")
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    delete = "--yes" in sys.argv
    raise SystemExit(asyncio.run(run(delete)))


if __name__ == "__main__":
    main()
