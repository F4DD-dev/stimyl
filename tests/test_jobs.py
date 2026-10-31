import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.models import Job
from app.db.session import make_engine, make_session_factory
from app.jobs import claim, dedup_key, enqueue, finish, release_stuck
from app.worker import heartbeat_loop
from tests.support import message


@pytest.fixture
async def factory(database_url: str):
    await __import__("tests.conftest", fromlist=["truncate"]).truncate(database_url)
    engine = make_engine(database_url)
    made = make_session_factory(engine)
    yield made
    await engine.dispose()


async def test_duplicate_update_is_one_job(factory):
    payload = message(1, "Аня", "дроби", "same-mid")
    async with factory() as session:
        await enqueue(session, payload)
        await enqueue(session, payload)
        await session.commit()
        count = await session.scalar(select(func.count()).select_from(Job))
    assert count == 1
    assert dedup_key(payload) == "mid:same-mid"


async def test_two_messages_from_one_user_stay_in_order(factory):
    first = message(7, "Ира", "первое", "m-1")
    second = message(7, "Ира", "второе", "m-2")
    async with factory() as session:
        await enqueue(session, first)
        await enqueue(session, second)
        await session.commit()
        claimed = await claim(session)
        await session.commit()
        assert claimed is not None
        assert json.loads(claimed.payload)["message"]["body"]["text"] == "первое"
        waiting = await claim(session)
        await session.commit()
        assert waiting is None
    async with factory() as session:
        row = await session.get(Job, claimed.id)
        await finish(session, row)
        await session.commit()
        nxt = await claim(session)
        await session.commit()
        assert nxt is not None
        assert json.loads(nxt.payload)["message"]["body"]["text"] == "второе"


async def test_crashed_worker_returns_the_job_to_the_queue(factory):
    old = datetime.now(UTC) - timedelta(minutes=5)
    async with factory() as session:
        session.add(
            Job(
                dedup_key="mid:crashed",
                user_key="9",
                payload='{"update_type":"message_created"}',
                status="running",
                attempts=0,
                run_at=old,
                locked_at=old,
                created_at=old,
            )
        )
        await session.commit()
        claimed = await claim(session)
        await session.commit()
        assert claimed is not None
        row = await session.get(Job, claimed.id)
    assert claimed.dedup_key == "mid:crashed"
    assert row.status == "running"
    assert row.attempts == 1


async def test_two_workers_do_not_claim_one_job(factory):
    import asyncio

    payload = message(3, "Оля", "дроби", "once")
    async with factory() as session:
        await enqueue(session, payload)
        await session.commit()

    async def take():
        async with factory() as session:
            job = await claim(session)
            await asyncio.sleep(0.05)
            await session.commit()
            return None if job is None else job.id

    first, second = await asyncio.gather(take(), take())
    assert (first is None) ^ (second is None)


async def test_stuck_job_returns_and_then_dies(factory):
    old = datetime.now(UTC) - timedelta(hours=2)
    async with factory() as session:
        session.add(
            Job(
                dedup_key="mid:stuck",
                user_key="9",
                payload="{}",
                status="running",
                attempts=4,
                run_at=old,
                locked_at=old,
                created_at=old,
            )
        )
        await session.commit()
        returned = await release_stuck(session)
        await session.commit()
        row = await session.scalar(select(Job).where(Job.dedup_key == "mid:stuck"))
    assert returned == 1
    assert row.status == "dead"
    assert row.last_error == "lease"


async def test_heartbeat_is_not_blocked_by_work(database_url, factory):
    import asyncio

    from app.db.models import RuntimeFlag
    from app.jobs import HEARTBEAT_KEY

    task = asyncio.create_task(heartbeat_loop(factory, every=0.05))
    await asyncio.sleep(0.12)
    async with factory() as session:
        first = await session.scalar(
            select(RuntimeFlag.value).where(RuntimeFlag.key == HEARTBEAT_KEY)
        )
    await asyncio.sleep(0.12)
    async with factory() as session:
        second = await session.scalar(
            select(RuntimeFlag.value).where(RuntimeFlag.key == HEARTBEAT_KEY)
        )
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert first is not None
    assert second is not None
    assert int(second) >= int(first)
