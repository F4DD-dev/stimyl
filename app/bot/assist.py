"""Разбор вопроса ученика моделью. Код решает, что показать и какой эталон принять.

В модель уходит только текст вопроса, распознанное условие и фрагменты урока класса.
Имя, телефон и id ученика туда не попадают. Учителю ничего из этого не уходит."""

import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Message, Topic
from app.domain.assist import LessonDraft, TaskDraft, leaks, match_topic, same_problem
from app.domain.curriculum import topic_by_title
from app.domain.images import MIME, image_kind, strip_metadata
from app.domain.library import class_of_student, find_fragments
from app.domain.tasks import GeneratedTask, generate_task
from app.domain.training import (
    TrainState,
    Turn,
    guided_direct,
    guided_lesson,
    guided_notice,
    guided_task,
)
from app.llm.explainer import Explainer

PRACTICE_ACTIONS = {"to_practice", "again", "skip"}


def wants_guide(state: TrainState, *, text: str, photo: bool) -> bool:
    """Модель разбирает новый вопрос или фото в тренировке. Ответ на открытое задание проверяет код."""
    if state.mode == "submission":
        return False
    if state.step == "check" and state.pending_answer and not photo:
        return False
    return bool(text.strip()) or photo


def wants_practice(state: TrainState, action: str) -> bool:
    return (
        state.mode != "submission"
        and action in PRACTICE_ACTIONS
        and bool(state.topic_title)
        and topic_by_title(state.topic_title or "") is None
    )


async def _history(session: AsyncSession, session_id: int | None) -> list[tuple[str, str]]:
    if session_id is None:
        return []
    rows = (
        await session.execute(
            select(Message.role, Message.text)
            .where(Message.session_id == session_id, Message.visibility == "private")
            .order_by(Message.id.desc())
            .limit(6)
        )
    ).all()
    return [(role, text) for role, text in reversed(rows)]


async def _topic_titles(session: AsyncSession) -> list[str]:
    return list(await session.scalars(select(Topic.title).order_by(Topic.position)))


def _as_task(task: TaskDraft, level: str) -> GeneratedTask:
    return GeneratedTask(task.prompt, task.answer, task.hint, level, task.first_step)


def clean_photo(blob: bytes | None) -> tuple[bytes, str] | None:
    if not blob:
        return None
    kind = image_kind(blob)
    if kind is None:
        return None
    return strip_metadata(blob), MIME[kind]


async def guide(
    session: AsyncSession,
    tutor: Explainer,
    state: TrainState,
    *,
    user_id: int,
    session_id: int | None,
    text: str,
    photo: bytes | None,
    rng: random.Random | None = None,
) -> Turn | None:
    """None — модель недоступна, пусть отвечает обычный сценарий."""
    question = text.strip()
    image = clean_photo(photo)
    if photo is not None and image is None and not question:
        return guided_notice(state, "photo_unreadable")
    if not question and image is None:
        return None
    titles = await _topic_titles(session)
    class_id = await class_of_student(session, user_id)
    fragments = await find_fragments(session, class_id, question, limit=3) if question else []
    draft = await tutor.analyze(
        question, titles, fragments, await _history(session, session_id), image
    )
    if draft is None:
        return None
    if draft.unreadable:
        return guided_notice(state, "photo_unreadable")
    direct = (draft.direct_answer or "").strip()
    if direct:
        return guided_direct(state, direct)
    has_lesson = bool(draft.explanation.strip() or draft.example.strip())
    if draft.off_topic and not has_lesson:
        return guided_notice(state, "off_topic")
    title = match_topic(draft.topic, titles)
    if title is None and state.topic_title:
        title = match_topic(state.topic_title, titles) or state.topic_title
    if title is None:
        title = _custom_title(draft.topic)
    if title is None:
        if has_lesson:
            title = state.topic_title or "Вопрос"
        else:
            return guided_notice(state, "unknown_topic", topics=True)
    explanation, example = _safe_text(draft, title)
    task = await _pick_task(tutor, draft, title, state.level, rng)
    return guided_lesson(state, title, explanation, example, task)


def _custom_title(raw: str | None) -> str | None:
    """Тема вне банка тем: короткая формулировка от модели, без мусора."""
    text = " ".join((raw or "").split()).strip(" .«»\"'")
    if not text or len(text) > 80 or text.casefold() in {"null", "none", "нет"}:
        return None
    return text[:80]


def _safe_text(draft: LessonDraft, title: str) -> tuple[str, str]:
    """Объяснение, где назван ответ задачи ученика, заменяем текстом программы."""
    explanation, example = draft.explanation, draft.example
    if leaks(explanation, draft.original_answer):
        bank = topic_by_title(title)
        explanation = bank.explanation if bank else ""
    if leaks(example, draft.original_answer):
        example = ""
    return explanation, example


async def _pick_task(
    tutor: Explainer,
    draft: LessonDraft,
    title: str,
    level: str,
    rng: random.Random | None,
) -> GeneratedTask | None:
    """Тема из программы — задание из шаблона, эталон считает код, запроса к модели нет.
    Тема вне банка — задание модели, если второе решение дало тот же ответ."""
    if topic_by_title(title) is not None:
        return generate_task(title, level, rng or random.Random())
    candidate = draft.task
    if candidate is None or same_problem(candidate, draft.original_answer):
        return None
    return _as_task(candidate, level) if await tutor.confirm(candidate) else None


async def practice(
    session: AsyncSession, tutor: Explainer, state: TrainState, *, user_id: int
) -> Turn:
    """Задание по теме вне банка: модель предлагает, код принимает эталон после второго решения."""
    title = state.topic_title or ""
    class_id = await class_of_student(session, user_id)
    fragments = await find_fragments(session, class_id, title, limit=2)
    made = await tutor.make_task(title, state.level, fragments)
    if made is None:
        return guided_notice(state, "no_task", topics=True)
    return guided_task(state, _as_task(made, state.level))
