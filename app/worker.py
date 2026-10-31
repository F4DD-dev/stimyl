"""Второй процесс контейнера: разбирает jobs и отмечает, что жив."""

import asyncio
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.service import process_update
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import Job, RuntimeFlag
from app.db.session import make_engine, make_session_factory
from app.jobs import HEARTBEAT_KEY, claim, fail, finish, payload_of
from app.llm.explainer import build_explainer
from app.max_client.base import NullSender
from app.max_client.client import DeliveryBlocked, DeliveryRetry, MaxClient

logger = logging.getLogger(__name__)


async def beat(session: AsyncSession) -> None:
    row = await session.get(RuntimeFlag, HEARTBEAT_KEY)
    value = str(int(time.time()))
    if row is None:
        session.add(RuntimeFlag(key=HEARTBEAT_KEY, value=value))
    else:
        row.value = value


async def run_available(
    factory: async_sessionmaker[AsyncSession],
    sender: object,
    explainer: object,
    settings: object,
    *,
    limit: int = 20,
) -> int:
    """Разобрать пачку готовых задач. Возвращает, сколько задач взято."""
    taken = 0
    for _ in range(limit):
        async with factory() as session:
            job = await claim(session)
            await session.commit()
            if job is None:
                return taken
            job_id = job.id
            update = payload_of(job)
        taken += 1
        try:
            async with factory() as session:
                await process_update(session, update, sender, explainer, settings)
                await session.commit()
            async with factory() as session:
                row = await session.get(Job, job_id)
                if row is not None:
                    await finish(session, row)
                await session.commit()
        except DeliveryBlocked:
            logger.error("delivery blocked")
            async with factory() as session:
                row = await session.get(Job, job_id)
                if row is not None:
                    await fail(session, row, "blocked", permanent=True)
                await session.commit()
        except DeliveryRetry:
            logger.error("delivery retry")
            async with factory() as session:
                row = await session.get(Job, job_id)
                if row is not None:
                    await fail(session, row, "retry", permanent=False)
                await session.commit()
        except Exception as exc:
            logger.error("job failed: %s", type(exc).__name__)
            async with factory() as session:
                row = await session.get(Job, job_id)
                if row is not None:
                    await fail(session, row, type(exc).__name__, permanent=False)
                await session.commit()
    return taken


async def heartbeat_loop(factory: async_sessionmaker[AsyncSession], every: float = 5) -> None:
    """Отметка живого воркера не ждёт разбор сообщения. Обрыв базы не завершает процесс."""
    while True:
        try:
            async with factory() as session:
                await beat(session)
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("worker heartbeat failed: %s", type(exc).__name__)
        await asyncio.sleep(every)


async def serve() -> None:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required")
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    if settings.max_token:
        sender = MaxClient(settings.max_token, settings.resolved_ca_path())
    else:
        sender = NullSender()
    explainer = build_explainer(settings)
    heart = asyncio.create_task(heartbeat_loop(factory))
    try:
        while True:
            try:
                await run_available(factory, sender, explainer, settings)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("worker loop: %s", type(exc).__name__)
                await asyncio.sleep(2)
                continue
            await asyncio.sleep(0.2)
    finally:
        heart.cancel()
        await sender.aclose()
        await engine.dispose()


def main() -> None:
    configure_logging()
    asyncio.run(serve())


if __name__ == "__main__":
    main()
