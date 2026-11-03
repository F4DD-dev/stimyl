from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.progress import STATUS_LABEL
from app.domain.status import TopicStatus


@dataclass(frozen=True)
class TopicColumn:
    title: str
    position: int


@dataclass(frozen=True)
class Cell:
    title: str
    status: str | None
    correct_percent: int | None
    stalled: bool


@dataclass(frozen=True)
class StudentRow:
    display_name: str
    cells: tuple[Cell, ...]
    activity: str = ""


@dataclass(frozen=True)
class ClassReport:
    class_title: str
    topics: tuple[TopicColumn, ...]
    students: tuple[StudentRow, ...]
    priorities: tuple[str, ...]
    frequent_mistakes: str | None
    stalled: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "class_title": self.class_title,
            "topics": [{"title": topic.title} for topic in self.topics],
            "students": [
                {
                    "display_name": student.display_name,
                    "activity": student.activity,
                    "topics": [
                        {
                            "title": cell.title,
                            "status": cell.status,
                            "correct_percent": cell.correct_percent,
                            "stalled": cell.stalled,
                        }
                        for cell in student.cells
                    ],
                }
                for student in self.students
            ],
            "priorities": list(self.priorities),
            "frequent_mistakes": self.frequent_mistakes,
            "stalled": list(self.stalled),
        }


@dataclass(frozen=True)
class StateFact:
    status: TopicStatus
    correct_percent: int
    last_attempt_on: date


def activity_line(
    *,
    mode: str | None,
    step: str | None,
    title: str | None,
    open_work: str | None,
) -> str:
    """What the teacher may see. Never a private message."""
    if mode == "training" and step in {"explain", "practice", "check"} and title:
        return f"Сейчас разбирает «{title}»"
    if mode == "submission" and step and step != "done" and title:
        return f"Сдаёт «{title}»"
    if open_work:
        return f"Не сдал «{open_work}»"
    if title and step == "done":
        return f"Последнее занятие: «{title}»"
    return "Ещё не открывал темы"


def build_report(
    class_title: str,
    topics: list[TopicColumn],
    students: list[str],
    states: dict[tuple[str, str], StateFact],
    wrong_counts: dict[str, int],
    today: date,
    stall_days: int = 7,
    activity: dict[str, str] | None = None,
) -> ClassReport:
    ordered_topics = tuple(sorted(topics, key=lambda topic: topic.position))
    horizon = today - timedelta(days=stall_days)
    rows: list[StudentRow] = []
    stalled: list[str] = []
    repeat_names: dict[str, list[str]] = {topic.title: [] for topic in ordered_topics}
    for name in students:
        cells: list[Cell] = []
        for topic in ordered_topics:
            fact = states.get((name, topic.title))
            if fact is None:
                cells.append(Cell(topic.title, None, None, False))
                continue
            is_stalled = (
                fact.status not in {TopicStatus.mastered, TopicStatus.started}
                and fact.last_attempt_on <= horizon
            )
            percent = None if fact.status is TopicStatus.started else fact.correct_percent
            cells.append(Cell(topic.title, fact.status.value, percent, is_stalled))
            if fact.status is TopicStatus.repeat:
                repeat_names[topic.title].append(name)
            if is_stalled:
                stalled.append(
                    f"{name} — {topic.title}, последняя попытка {fact.last_attempt_on:%d.%m}"
                )
        rows.append(StudentRow(name, tuple(cells), (activity or {}).get(name, "")))

    priorities = tuple(
        f"{title}: {STATUS_LABEL[TopicStatus.repeat]}, {', '.join(names)}"
        for title, names in repeat_names.items()
        if names
    )
    frequent = None
    if wrong_counts:
        title = max(wrong_counts, key=lambda item: (wrong_counts[item], item))
        if wrong_counts[title] > 0:
            frequent = f"Чаще всего ошибки в теме «{title}»."
    return ClassReport(
        class_title=class_title,
        topics=ordered_topics,
        students=tuple(rows),
        priorities=priorities,
        frequent_mistakes=frequent,
        stalled=tuple(stalled),
    )
