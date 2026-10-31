"""Статус темы считает код. Окно — последние 10 попыток."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class TopicStatus(StrEnum):
    started = "started"
    mastered = "mastered"
    needs_practice = "needs_practice"
    repeat = "repeat"


@dataclass(frozen=True)
class Thresholds:
    repeat_below: float = 0.5
    mastered_from: float = 0.8


@dataclass(frozen=True)
class Mark:
    credit: float
    correct: bool
    prompt: str
    at: datetime | None = None


def mark_of(
    correct: bool,
    *,
    hinted: bool = False,
    prompt: str = "",
    at: datetime | None = None,
) -> Mark:
    if correct and hinted:
        credit = 0.5
    elif correct:
        credit = 1.0
    else:
        credit = 0.0
    return Mark(credit, correct, prompt, at)


def correct_ratio(flags: list[bool]) -> float:
    if not flags:
        return 0.0
    return sum(1 for flag in flags if flag) / len(flags)


def decide_status(marks: list[Mark], thresholds: Thresholds | None = None) -> TopicStatus | None:
    """Меньше трёх попыток — начато, без процента как вердикта.

    Повторить: доля верных ниже 50% или две последние попытки неверные.
    Усвоено: доля от 80% и верный ответ на другом варианте не раньше чем через 12 часов.
    Иначе нужна практика. Верный ответ после подсказки даёт 0,5.
    """
    if not marks:
        return None
    if len(marks) < 3:
        return TopicStatus.started
    rules = thresholds or Thresholds()
    window = marks[-10:]
    score = sum(item.credit for item in window) / len(window)
    last_two_wrong = not window[-1].correct and not window[-2].correct
    if score < rules.repeat_below or last_two_wrong:
        return TopicStatus.repeat
    if score >= rules.mastered_from and _spaced(window):
        return TopicStatus.mastered
    return TopicStatus.needs_practice


def show_percent(status: TopicStatus | None) -> bool:
    return status not in {None, TopicStatus.started}


def _spaced(window: list[Mark]) -> bool:
    corrects = [item for item in window if item.correct and item.at is not None]
    gap = timedelta(hours=12)
    for earlier, later in zip(corrects, corrects[1:], strict=False):
        if earlier.prompt != later.prompt and later.at - earlier.at >= gap:
            return True
    return False
