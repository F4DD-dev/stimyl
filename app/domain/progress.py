from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.status import TopicStatus

STATUS_LABEL = {
    TopicStatus.started: "начато",
    TopicStatus.mastered: "усвоено",
    TopicStatus.needs_practice: "нужна практика",
    TopicStatus.repeat: "повторить",
}

@dataclass(frozen=True)
class TopicProgress:
    title: str
    position: int
    status: TopicStatus | None
    correct_percent: int | None
    attempts: int = 0
    rank_score: float | None = None


@dataclass(frozen=True)
class NextStep:
    topic_title: str
    label: str


def streak(days: set[date], today: date) -> int:
    if today in days:
        cursor = today
    elif today - timedelta(days=1) in days:
        cursor = today - timedelta(days=1)
    else:
        return 0
    count = 0
    while cursor in days:
        count += 1
        cursor -= timedelta(days=1)
    return count


def _rank(row: TopicProgress) -> float:
    if row.rank_score is not None:
        return row.rank_score
    if row.correct_percent is None:
        return 1.0
    return row.correct_percent / 100


def choose_next(rows: list[TopicProgress]) -> NextStep | None:
    if not rows:
        return None
    ranked = [row for row in rows if row.attempts > 0 or row.status is not None]
    if not ranked:
        first = min(rows, key=lambda row: row.position)
        return NextStep(first.title, f"Разобрать тему «{first.title}»")
    worst = min(ranked, key=lambda row: (_rank(row), row.position))
    if worst.status is TopicStatus.started:
        label = f"Продолжить тему «{worst.title}»"
    elif worst.status is TopicStatus.repeat:
        label = f"Повторить тему «{worst.title}»"
    elif worst.status is TopicStatus.needs_practice:
        label = f"Потренировать тему «{worst.title}»"
    else:
        label = f"Закрепить тему «{worst.title}»"
    return NextStep(worst.title, label)
