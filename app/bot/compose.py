"""Работа для учителя: модель предлагает задания, код сверяет эталон, учитель решает, отправлять ли.
В промпт уходят только тема, цель и фрагменты материала. Тексты учеников сюда не попадают."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.assist import TeacherAsk, match_topic
from app.domain.drafts import build_check_draft, build_stimul_draft
from app.domain.library import find_fragments, has_materials, recent_fragments
from app.domain.report import ClassReport
from app.domain.schoolwork import list_teacher_works
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
    subject: str = "",
) -> Composed:
    fragments: list[str] = []
    if use_material:
        if not await has_materials(session, class_id):
            return Composed(None, MATERIAL_MISSING, 409)
        fragments = await find_fragments(session, class_id, f"{topic} {goal}", limit=6)
        if not fragments:
            return Composed(None, MATERIAL_NO_MATCH, 409)
    if tutor.enabled:
        drafted = await tutor.draft_work(
            topic, goal, count, difficulty, fragments, subject
        )
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


def _weak_ranking(report: ClassReport) -> list[tuple[str, list[int]]]:
    weak: dict[str, list[int]] = {}
    for student in report.students:
        for cell in student.cells:
            bag = weak.setdefault(cell.title, [0, 0])
            if cell.status == TopicStatus.repeat.value:
                bag[0] += 1
            elif cell.status == TopicStatus.needs_practice.value:
                bag[1] += 1
    return sorted(
        ((title, bag) for title, bag in weak.items() if bag[0] or bag[1]),
        key=lambda item: (-item[1][0], -item[1][1], item[0]),
    )


def weak_topic_titles(report: ClassReport) -> list[str]:
    """Темы класса по слабости: сначала «повторить», потом «нужна практика»."""
    return [title for title, _bag in _weak_ranking(report)]


async def pick_topic(
    session: AsyncSession,
    tutor: Explainer,
    report: ClassReport,
    ask: TeacherAsk,
    *,
    class_id: int | None,
) -> str:
    """Тема для работы: из запроса, из материала или самая слабая тема класса."""
    titles = [topic.title for topic in report.topics]
    matched = match_topic(ask.topic, titles)
    if matched:
        return matched
    if ask.topic:
        return ask.topic
    if ask.use_material or await has_materials(session, class_id):
        fragments = await recent_fragments(session, class_id)
        guessed = await tutor.topic_from_fragments(fragments) if tutor.enabled else None
        if guessed:
            return match_topic(guessed, titles) or guessed
    weak = weak_topic_titles(report)
    if weak:
        return weak[0]
    return titles[0] if titles else ""


def class_context(report: ClassReport) -> str:
    """Факты о классе для промпта: модель отвечает только по ним, ничего не выдумывая."""
    subjects = sorted({topic.subject_title for topic in report.topics if topic.subject_title})
    return (
        f"Класс: {report.class_title or 'не указан'}. "
        f"Учеников в классе: {len(report.students)}. "
        f"Предметы: {', '.join(subjects) if subjects else 'не назначены'}. "
        f"Тем в программе: {len(report.topics)}."
    )


_STATUS_RU = {
    "mastered": "усвоено",
    "needs_practice": "нужна практика",
    "repeat": "повторить",
    "started": "в процессе",
}


async def classroom_context(
    session: AsyncSession,
    teacher,
    class_id: int | None,
    report: ClassReport,
) -> str:
    """Полный срез класса для ответов помощника: ученики, темы, работы.
    Только агрегаты и статусы — личная переписка сюда не попадает."""
    lines = [class_context(report)]
    by_subject: dict[str, list[str]] = {}
    for topic in report.topics:
        by_subject.setdefault(topic.subject_title or "Без предмета", []).append(topic.title)
    if by_subject:
        lines.append("Темы по предметам:")
        for subject, titles in by_subject.items():
            lines.append(f"- {subject}: {', '.join(titles)}")
    if report.students:
        lines.append("Ученики и прогресс:")
        for student in report.students[:15]:
            counts: dict[str, int] = {}
            weak: list[str] = []
            for cell in student.cells:
                key = cell.status or "none"
                counts[key] = counts.get(key, 0) + 1
                if cell.status in {"needs_practice", "repeat"}:
                    weak.append(cell.title)
            parts = [
                f"{_STATUS_RU.get(key, key)} {count}"
                for key, count in counts.items()
                if key != "none" and count
            ]
            detail = ", ".join(parts) or "попыток нет"
            if weak:
                detail += f"; слабые темы: {', '.join(weak[:4])}"
            activity = f"; сейчас: {student.activity}" if student.activity else ""
            lines.append(f"- {student.display_name}: {detail}{activity}")
        if len(report.students) > 15:
            lines.append(f"- …и ещё {len(report.students) - 15}")
    try:
        works = await list_teacher_works(session, teacher, class_id)
    except Exception:
        works = []
    published = [work for work in works if work.get("status") == "published"][:8]
    drafts = [work for work in works if work.get("status") != "published"][:5]
    if published or drafts:
        lines.append("Работы:")
        for work in published:
            handed = work.get("handed") or []
            line = (
                f"- «{work.get('title')}» ({work.get('subject') or 'без предмета'}): "
                f"опубликована, сдали {work.get('done')}/{work.get('recipients')}"
            )
            if handed:
                line += f", сдали: {', '.join(handed)}"
            lines.append(line)
        for work in drafts:
            lines.append(
                f"- «{work.get('title')}» ({work.get('subject') or 'без предмета'}): черновик"
            )
    return "\n".join(lines)


def class_summary(report: ClassReport) -> str:
    """Сводка по статусам, посчитанная кодом. Без текстов учеников."""
    ranked = _weak_ranking(report)
    if not ranked:
        return "Слабых тем сейчас нет: у учеников либо «усвоено», либо ещё нет попыток."
    lines = [
        f"«{title}»: повторить {bag[0]}, нужна практика {bag[1]}" for title, bag in ranked[:4]
    ]
    text = "Слабее всего:\n" + "\n".join(lines)
    if report.frequent_mistakes:
        text = f"{text}\n{report.frequent_mistakes}"
    return text
