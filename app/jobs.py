"""Очередь входящих апдейтов. Повтор с тем же ключом не создаёт вторую строку."""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models import Job

HEARTBEAT_KEY = "worker_heartbeat"
MAX_ATTEMPTS = 5
LEASE = timedelta(seconds=60)


def user_key_of(update: dict) -> str:
    kind = update.get("update_type")
    if kind == "message_created":
        uid = ((update.get("message") or {}).get("sender") or {}).get("user_id")
    elif kind == "message_callback":
        uid = ((update.get("callback") or {}).get("user") or {}).get("user_id")
    elif kind == "bot_started":
        uid = (update.get("user") or {}).get("user_id")
    else:
        uid = None
    return "" if uid is None else str(uid)[:64]


def dedup_key(update: dict) -> str:
    kind = update.get("update_type")
    if kind == "message_callback":
        callback = update.get("callback") or {}
        callback_id = callback.get("callback_id")
        if callback_id:
            return f"cb:{callback_id}"[:200]
    if kind == "message_created":
        body = (update.get("message") or {}).get("body") or {}
        mid = body.get("mid")
        if mid:
            return f"mid:{mid}"[:200]
    if kind == "bot_started":
        user = update.get("user") or {}
        return f"start:{user.get('user_id')}:{update.get('chat_id')}:{update.get('timestamp')}"[:200]
    raw = json.dumps(update, ensure_ascii=False, sort_keys=True, default=str)
    return "raw:" + raw[:180]


def _now() -> datetime:
    return datetime.now(UTC)


async def enqueue(session: AsyncSession, update: dict) -> None:
    key = dedup_key(update)
    found = await session.scalar(select(Job.id).where(Job.dedup_key == key))
    if found is not None:
        return
    now = _now()
    try:
        async with session.begin_nested():
            session.add(
                Job(
                    dedup_key=key,
                    user_key=user_key_of(update),
                    payload=json.dumps(update, ensure_ascii=False),
                    status="pending",
                    attempts=0,
                    run_at=now,
                    created_at=now,
                )
            )
            await session.flush()
    except IntegrityError:
        return


async def release_stuck(session: AsyncSession, *, lease: timedelta = LEASE) -> int:
    """Вернуть задачи, которые воркер не отпустил. Слишком много раз — dead."""
    now = _now()
    rows = list(
        await session.scalars(
            select(Job).where(
                Job.status == "running",
                Job.locked_at.is_not(None),
                Job.locked_at < now - lease,
            )
        )
    )
    for job in rows:
        job.attempts += 1
        job.last_error = "lease"
        job.locked_at = None
        if job.attempts >= MAX_ATTEMPTS:
            job.status = "dead"
        else:
            job.status = "pending"
            job.run_at = now
    return len(rows)


async def claim(session: AsyncSession) -> Job | None:
    """Один активный job на пользователя, строго по порядку id."""
    await release_stuck(session)
    now = _now()
    candidate = aliased(Job)
    running_same = (
        select(Job.id)
        .where(
            Job.user_key == candidate.user_key,
            Job.user_key != "",
            Job.status == "running",
        )
        .exists()
    )
    earlier = (
        select(Job.id)
        .where(
            Job.user_key == candidate.user_key,
            Job.user_key != "",
            Job.status == "pending",
            Job.run_at <= now,
            Job.id < candidate.id,
        )
        .exists()
    )
    stmt = (
        select(candidate)
        .where(
            candidate.status == "pending",
            candidate.run_at <= now,
            ~running_same,
            ~earlier,
        )
        .order_by(candidate.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = await session.scalar(stmt)
    if job is None:
        return None
    job.status = "running"
    job.locked_at = now
    await session.flush()
    return job


def payload_of(job: Job) -> dict:
    data = json.loads(job.payload)
    if not isinstance(data, dict):
        return {}
    return data


async def finish(session: AsyncSession, job: Job) -> None:
    job.status = "done"
    job.last_error = None


async def fail(session: AsyncSession, job: Job, reason: str, *, permanent: bool) -> None:
    job.attempts += 1
    job.last_error = reason[:200]
    if permanent or job.attempts >= MAX_ATTEMPTS:
        job.status = "dead"
        return
    job.status = "pending"
    job.run_at = _now() + timedelta(seconds=2**job.attempts)
