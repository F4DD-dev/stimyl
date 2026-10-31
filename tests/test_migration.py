import asyncio
import os
import uuid

import asyncpg
from alembic.config import Config

from alembic import command
from tests.conftest import postgres_url


def _admin_dsn(url: str) -> str:
    raw = url.replace("postgresql+asyncpg://", "postgresql://")
    return raw.rsplit("/", 1)[0] + "/postgres"


async def _create(base: str, name: str) -> None:
    conn = await asyncpg.connect(_admin_dsn(base))
    try:
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


async def _drop(base: str, name: str) -> None:
    conn = await asyncpg.connect(_admin_dsn(base))
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1",
            name,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        await conn.close()


def test_migrations_roundtrip_on_postgres():
    """Синхронный тест: alembic сам вызывает asyncio.run."""
    base = postgres_url()
    name = "stimul_mig_" + uuid.uuid4().hex[:8]
    asyncio.run(_create(base, name))
    url = _admin_dsn(base).rsplit("/", 1)[0] + "/" + name
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    config = Config("alembic.ini")
    try:
        command.upgrade(config, "head")
        command.downgrade(config, "-1")
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        asyncio.run(_drop(base, name))
