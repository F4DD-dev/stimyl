from dataclasses import dataclass
from enum import StrEnum


class TopicStatus(StrEnum):
    mastered = "mastered"
    needs_practice = "needs_practice"
    repeat = "repeat"


@dataclass(frozen=True)
class Thresholds:
    repeat_below: float = 0.5
    mastered_from: float = 0.8


def correct_ratio(flags: list[bool]) -> float:
    if not flags:
        return 0.0
    return sum(1 for flag in flags if flag) / len(flags)


def has_successful_recheck(flags: list[bool]) -> bool:
    """A later attempt is correct. The first attempt alone is not a recheck."""
    return any(flags[1:])


def decide_status(flags: list[bool], thresholds: Thresholds | None = None) -> TopicStatus | None:
    """Status from every attempt on the topic. No sliding window.

    No attempts means there is no status row. That is not a fourth status.
    Repeat wins when the ratio is below the floor or the last two checks failed.
    Mastered needs the high ratio and a successful later check.
    Everything else with at least one attempt is needs_practice.
    """
    if not flags:
        return None
    rules = thresholds or Thresholds()
    ratio = correct_ratio(flags)
    two_failures = len(flags) >= 2 and not flags[-1] and not flags[-2]
    if ratio < rules.repeat_below or two_failures:
        return TopicStatus.repeat
    if ratio >= rules.mastered_from and has_successful_recheck(flags):
        return TopicStatus.mastered
    return TopicStatus.needs_practice


def percent(flags: list[bool]) -> int:
    return round(correct_ratio(flags) * 100)
