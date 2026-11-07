"""Решённые учеником задания. Только его собственные строки и никогда эталон."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Attempt, Topic
from app.domain.training import SEEN_LIMIT

HISTORY_LIMIT = 20


async def solved_prompts(session: AsyncSession, user_id: int, topic_title: str | None) -> list[str]:
    """Условия, на которые ученик уже отвечал по этой теме, свежие первыми."""
    if not topic_title:
        return []
    rows = await session.scalars(
        select(Attempt.prompt)
        .join(Topic, Topic.id == Attempt.topic_id)
        .where(Attempt.user_id == user_id, Topic.title == topic_title)
        .order_by(Attempt.id.desc())
        .limit(SEEN_LIMIT)
    )
    return list(dict.fromkeys(rows))


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.isoformat()


async def student_attempts(
    session: AsyncSession,
    user_id: int,
    *,
    limit: int = HISTORY_LIMIT,
    before: int | None = None,
) -> dict:
    """История решённых примеров ученика: условие, его ответ, верно или нет."""
    query = (
        select(
            Attempt.id,
            Attempt.prompt,
            Attempt.answer,
            Attempt.correct,
            Attempt.hinted,
            Attempt.mode,
            Attempt.created_at,
            Topic.title,
        )
        .outerjoin(Topic, Topic.id == Attempt.topic_id)
        .where(Attempt.user_id == user_id)
    )
    if before is not None:
        query = query.where(Attempt.id < before)
    rows = (await session.execute(query.order_by(Attempt.id.desc()).limit(limit + 1))).all()
    items = [
        {
            "id": row_id,
            "topic": title,
            "prompt": prompt,
            "answer": answer,
            "correct": bool(correct),
            "hinted": bool(hinted),
            "mode": mode,
            "created_at": _iso(created_at),
        }
        for row_id, prompt, answer, correct, hinted, mode, created_at, title in rows[:limit]
    ]
    return {"items": items, "more": len(rows) > limit}
