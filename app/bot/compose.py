"""Работа для учителя: модель предлагает задания, код сверяет эталон, учитель решает, отправлять ли.
В промпт уходят только тема, цель и фрагменты материала. Тексты учеников сюда не попадают."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.drafts import build_check_draft, build_stimul_draft
from app.domain.library import find_fragments, has_materials
from app.domain.report import ClassReport
from app.domain.status import TopicStatus
from app.llm.explainer import Explainer

MATERIAL_MISSING = (
    "Нет сохранённых фрагментов урока. "
    "Не собираю задания по параграфу и не выдумываю источник."
)
MATERIAL_NO_MATCH = (
    "В загруженных материалах нет фрагментов по этой теме. "
    "Загрузите нужный параграф или соберите работу без материала."
)
NO_BANK = "По этой теме задания сам не соберу. Напишите вопросы и верные ответы."
ASSISTANT_OFF = "Помощник сейчас недоступен. Работу можно собрать в разделе «Задания»."


@dataclass
class Composed:
    draft: dict | None
    error: str | None = None
    status: int = 200


async def compose_draft(
    session: AsyncSession,
    tutor: Explainer,
    *,
    class_id: int | None,
    topic: str,
    goal: str,
    count: int,
    difficulty: str,
    audience: str,
    students: list[str],
    use_material: bool,
) -> Composed:
    fragments: list[str] = []
    if use_material:
        if not await has_materials(session, class_id):
            return Composed(None, MATERIAL_MISSING, 409)
        fragments = await find_fragments(session, class_id, f"{topic} {goal}", limit=6)
        if not fragments:
            return Composed(None, MATERIAL_NO_MATCH, 409)
    if tutor.enabled:
        drafted = await tutor.draft_work(topic, goal, count, difficulty, fragments)
        if drafted:
            return Composed(_ai_draft(topic, goal, count, difficulty, audience, students, drafted, fragments))
    if use_material:
        return Composed(None, ASSISTANT_OFF, 503)
    draft = build_check_draft(topic, goal, count, difficulty, audience, students)
    if draft is None:
        draft = build_stimul_draft(topic, goal, count, difficulty, audience, students)
    if draft is None:
        return Composed(None, NO_BANK, 409)
    for item in draft["items"]:
        item["checked"] = True
    return Composed(draft)


def _ai_draft(topic, goal, count, difficulty, audience, students, drafted, fragments) -> dict:
    items = []
    doubtful = []
    for index, (task, checked) in enumerate(drafted, start=1):
        items.append(
            {
                "number": index,
                "prompt": task.prompt,
                "choices": [],
                "reference": task.answer,
                "hint": task.hint,
                "checked": checked,
            }
        )
        if not checked:
            doubtful.append(str(index))
    note = "Задания по загруженному материалу." if fragments else ""
    if doubtful:
        warn = (
            f"Ответ к заданию {doubtful[0]} не сошёлся при повторном решении. Проверьте его."
            if len(doubtful) == 1
            else f"Ответы к заданиям {', '.join(doubtful)} не сошлись при повторном решении. Проверьте их."
        )
        note = f"{note} {warn}".strip()
    if len(items) < count:
        note = f"{note} Собралось {len(items)} из {count}.".strip()
    return {
        "topic": topic.strip(),
        "goal": goal.strip(),
        "count": len(items),
        "difficulty": difficulty,
        "audience": audience,
        "students": list(students),
        "items": items,
        "source": "material" if fragments else "stimul",
        "persisted": False,
        "note": note or None,
    }


def class_summary(report: ClassReport) -> str:
    """Сводка по статусам, посчитанная кодом. Без текстов учеников."""
    weak: dict[str, list[int]] = {}
    for student in report.students:
        for cell in student.cells:
            bag = weak.setdefault(cell.title, [0, 0])
            if cell.status == TopicStatus.repeat.value:
                bag[0] += 1
            elif cell.status == TopicStatus.needs_practice.value:
                bag[1] += 1
    ranked = sorted(
        ((title, bag) for title, bag in weak.items() if bag[0] or bag[1]),
        key=lambda item: (-item[1][0], -item[1][1], item[0]),
    )
    if not ranked:
        return "Слабых тем сейчас нет: у учеников либо «усвоено», либо ещё нет попыток."
    lines = [
        f"«{title}»: повторить {bag[0]}, нужна практика {bag[1]}" for title, bag in ranked[:4]
    ]
    text = "Слабее всего:\n" + "\n".join(lines)
    if report.frequent_mistakes:
        text = f"{text}\n{report.frequent_mistakes}"
    return text
