"""Сброс данных прототипа. По умолчанию только показывает план и ничего не удаляет.

Удаление возможно только вместе:
- аргумент --yes
- STIMUL_ALLOW_RESET=1
- STIMUL_RESET_DATABASE совпадает с именем базы в DATABASE_URL
- ENV не prod

Схему и таблицу alembic_version скрипт не трогает. На общую или боевую базу его не запускать.
"""

import asyncio
import os
import sys
from urllib.parse import urlparse

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import make_engine

TABLES = (
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
    "runtime_flags",
    "enrollments",
    "class_subject_teachers",
    "class_teachers",
    "staff_seats",
    "join_applications",
    "users",
    "topics",
    "subjects",
    "classes",
    "schools",
)


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
        listed = ", ".join(table for table, count in tallies if count >= 0)
        async with engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE TABLE {listed} RESTART IDENTITY CASCADE"))
        print("Строки удалены. alembic_version и структура таблиц на месте.")
        return 0
    finally:
        await engine.dispose()


def main() -> None:
    delete = "--yes" in sys.argv
    raise SystemExit(asyncio.run(run(delete)))


if __name__ == "__main__":
    main()
