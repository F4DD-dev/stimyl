"""Миграции под pg advisory lock. Второй процесс ждёт, а не пишет схему параллельно."""

import asyncio
import logging

from alembic.config import Config
from sqlalchemy import text

from alembic import command
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import make_engine

logger = logging.getLogger(__name__)

# Одно число на всё приложение. Сессионная блокировка, не транзакционная.
LOCK_KEY = 874221


def _upgrade_files() -> None:
    command.upgrade(Config("alembic.ini"), "head")


async def _upgrade_head() -> list[str]:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required")
    engine = make_engine(settings.database_url, null_pool=True)
    async with engine.connect() as connection:
        await connection.execute(text(f"SELECT pg_advisory_lock({LOCK_KEY})"))
        await connection.commit()
        try:
            await asyncio.to_thread(_upgrade_files)
            rows = await connection.execute(text("SELECT version_num FROM alembic_version"))
            applied = sorted(rows.scalars().all())
        finally:
            await connection.execute(text(f"SELECT pg_advisory_unlock({LOCK_KEY})"))
            await connection.commit()
    await engine.dispose()
    logger.info("migrations applied=%s", ",".join(applied) or "-")
    return applied


def upgrade_head() -> list[str]:
    """Синхронная обёртка: Alembic сам вызывает asyncio.run, поэтому из чужого цикла её зовут через поток."""
    return asyncio.run(_upgrade_head())


def main() -> None:
    configure_logging()
    try:
        applied = upgrade_head()
    except Exception as exc:
        logger.error("migrate failed: %s", type(exc).__name__)
        raise SystemExit(1) from None
    logger.info("migrate done count=%s", len(applied))


if __name__ == "__main__":
    main()
