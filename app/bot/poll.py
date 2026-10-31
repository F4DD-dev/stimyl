import asyncio
import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import RuntimeFlag
from app.db.session import make_engine, make_session_factory
from app.jobs import enqueue
from app.max_client.client import MaxClient

logger = logging.getLogger(__name__)
MARKER_KEY = "updates_marker"


async def poll() -> None:
    settings = get_settings()
    if not settings.max_token:
        raise SystemExit("MAX_TOKEN is required")
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    sender = MaxClient(settings.max_token, settings.resolved_ca_path())
    marker = await _read_marker(factory)
    try:
        while True:
            try:
                payload = await sender.get_updates(marker)
            except Exception as exc:
                logger.error("updates failed: %s", type(exc).__name__)
                await asyncio.sleep(1)
                continue
            saved = True
            async with factory() as session:
                try:
                    for update in payload.get("updates") or []:
                        if isinstance(update, dict):
                            logger.info("update %s", update.get("update_type"))
                            await enqueue(session, update)
                    await session.commit()
                except Exception as exc:
                    await session.rollback()
                    saved = False
                    logger.error("update failed: %s", type(exc).__name__)
            if not saved:
                await asyncio.sleep(1)
                continue
            next_marker = payload.get("marker")
            if isinstance(next_marker, int):
                marker = next_marker
                await _write_marker(factory, marker)
    finally:
        await sender.aclose()
        await engine.dispose()


async def _read_marker(factory) -> int | None:
    async with factory() as session:
        value = await session.scalar(select(RuntimeFlag.value).where(RuntimeFlag.key == MARKER_KEY))
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


async def _write_marker(factory, marker: int) -> None:
    async with factory() as session:
        row = await session.get(RuntimeFlag, MARKER_KEY)
        if row is None:
            session.add(RuntimeFlag(key=MARKER_KEY, value=str(marker)))
        else:
            row.value = str(marker)
        await session.commit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    asyncio.run(poll())


if __name__ == "__main__":
    main()
