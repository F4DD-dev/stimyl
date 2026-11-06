"""Учитель в чате MAX: просьба словами → черновик с ответами → «Отправить».
Ничего не уходит ученикам без нажатия кнопки. Эталон виден только учителю."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.compose import (
    ASSISTANT_OFF,
    class_summary,
    classroom_context,
    compose_draft,
    pick_topic,
)
from app.bot.gate import GateReply
from app.core.config import Settings
from app.db.models import Subject, User, Work, WorkItem, WorkRecipient
from app.domain.assist import match_students
from app.domain.schoolwork import owned_class, publish_work, save_work
from app.llm.explainer import Explainer

SEND = "tw_send"
AGAIN = "tw_again"
HELP = (
    "Напишите, какую работу собрать. Например: «Дроби, сложение с разными знаменателями, "
    "4 задания для Пети и Маши». Могу и подсказать, какие темы класса слабее."
)


def is_teacher_action(payload: str | None) -> bool:
    return bool(payload) and payload.split(":", 1)[0] in {SEND, AGAIN}


async def teacher_turn(
    session: AsyncSession,
    tutor: Explainer,
    teacher: User,
    settings: Settings,
    *,
    text: str | None,
    payload: str | None,
) -> list[GateReply]:
    from app.bot.service import class_report

    action, _, raw_id = (payload or "").partition(":")
    if action == SEND and raw_id.isdigit():
        return await _send(session, teacher, int(raw_id))
    if action == AGAIN and raw_id.isdigit():
        return await _again(session, tutor, teacher, int(raw_id))
    if not text:
        return [GateReply(HELP, (("Открыть кабинет", "open_cabinet"),))]
    report = await class_report(session, teacher, settings)
    if report is None:
        return [GateReply("Класс к вам ещё не привязан. Откройте кабинет, чтобы выбрать класс.")]
    context = await classroom_context(session, teacher, None, report)
    ask = await tutor.read_teacher(
        text, [topic.title for topic in report.topics], context=context
    )
    if ask is None:
        return [GateReply(ASSISTANT_OFF, (("Открыть кабинет", "open_cabinet"),))]
    if ask.intent == "summary":
        if tutor.enabled:
            grounded = (
                f"{context}\n\nСводка по темам (посчитана кодом):\n{class_summary(report)}"
            )
            reply = await tutor.teacher_reply(text, context=grounded)
            if reply:
                return [GateReply(reply, (("Собрать работу", "open_cabinet"),))]
        return [GateReply(class_summary(report), (("Собрать работу", "open_cabinet"),))]
    if ask.intent in {"chat", "other"}:
        reply = ask.reply or (
            await tutor.teacher_reply(text, context=context) if tutor.enabled else ""
        )
        return [GateReply(reply or HELP)]
    class_id = await owned_class(session, teacher, None)
    topic = await pick_topic(session, tutor, report, ask, class_id=class_id)
    if ask.intent != "work" or not topic:
        return [GateReply(HELP)]
    roster = [(student.user_id, student.display_name) for student in report.students]
    ids, names, unknown = match_students(list(ask.students), roster)
    audience = "selected" if ids else "class"
    composed = await compose_draft(
        session,
        tutor,
        class_id=class_id,
        topic=topic,
        goal=ask.goal or topic,
        count=ask.count,
        difficulty=ask.difficulty,
        audience=audience,
        students=names,
        use_material=ask.use_material,
    )
    if composed.error or composed.draft is None:
        return [GateReply(composed.error or ASSISTANT_OFF)]
    draft = composed.draft
    saved, error, _status = await save_work(
        session,
        teacher,
        class_id=class_id,
        topic=topic,
        goal=ask.goal or topic,
        count=len(draft["items"]),
        difficulty=ask.difficulty,
        audience=audience,
        students=names,
        student_ids=ids,
        prompts=None,
        due_at=None,
        own_items=[(item["prompt"], item["reference"]) for item in draft["items"]],
    )
    if error or saved is None:
        return [GateReply(error or "Черновик не сохранился.")]
    lead = _draft_text(saved, draft, names, unknown)
    return [GateReply(lead, _buttons(saved["id"], audience, len(names)))]


def _draft_text(saved: dict, draft: dict, names: list[str], unknown: list[str]) -> str:
    who = ", ".join(names) if names else "весь класс"
    lines = [f"Черновик: {saved['title']}. Кому: {who}.", ""]
    for item in saved["items"]:
        lines.append(f"{item['position']}. {item['prompt']}")
        lines.append(f"Ответ: {item['reference']}")
    if draft.get("note"):
        lines += ["", draft["note"]]
    if unknown:
        lines += ["", f"Не нашёл в классе: {', '.join(unknown)}."]
    lines += ["", "Ученики увидят только задания. Поправить формулировки можно в кабинете."]
    return "\n".join(lines)[:3900]


def _buttons(work_id: int, audience: str, picked: int) -> tuple[tuple[str, str], ...]:
    label = "Отправить классу" if audience == "class" else f"Отправить ({picked})"
    return (
        (label, f"{SEND}:{work_id}"),
        ("Собрать заново", f"{AGAIN}:{work_id}"),
        ("Открыть кабинет", "open_cabinet"),
    )


async def _send(session: AsyncSession, teacher: User, work_id: int) -> list[GateReply]:
    payload, error, _status = await publish_work(session, teacher, work_id)
    if error or payload is None:
        return [GateReply(error or "Работа не отправилась.")]
    return [
        GateReply(
            f"Отправил «{payload['title']}». Получателей: {payload['recipients']}. "
            "Когда ученики сдадут, результат появится в кабинете."
        )
    ]


async def _again(
    session: AsyncSession, tutor: Explainer, teacher: User, work_id: int
) -> list[GateReply]:
    work = await session.get(Work, work_id)
    if work is None or work.author_id != teacher.id:
        return [GateReply("Черновик не найден.")]
    if work.status != "draft":
        return [GateReply("Эта работа уже отправлена, её не пересобираю.")]
    count = len(list(await session.scalars(select(WorkItem.id).where(WorkItem.work_id == work.id))))
    ids = list(
        await session.scalars(select(WorkRecipient.user_id).where(WorkRecipient.work_id == work.id))
    )
    subject_title = ""
    if work.subject_id is not None:
        found = await session.get(Subject, work.subject_id)
        subject_title = found.title if found else ""
    composed = await compose_draft(
        session,
        tutor,
        class_id=work.class_id,
        topic=work.title,
        goal=work.goal,
        count=max(1, count),
        difficulty=work.difficulty,
        audience=work.audience,
        students=[],
        use_material=False,
        subject=subject_title,
    )
    if composed.error or composed.draft is None:
        return [GateReply(composed.error or ASSISTANT_OFF)]
    saved, error, _status = await save_work(
        session,
        teacher,
        class_id=work.class_id,
        topic=work.title,
        goal=work.goal,
        count=len(composed.draft["items"]),
        difficulty=work.difficulty,
        audience=work.audience,
        students=[],
        student_ids=ids,
        prompts=None,
        due_at=work.due_at,
        work_id=work.id,
        own_items=[(item["prompt"], item["reference"]) for item in composed.draft["items"]],
    )
    if error or saved is None:
        return [GateReply(error or "Черновик не сохранился.")]
    names = [
        name
        for name in await session.scalars(select(User.display_name).where(User.id.in_(ids)))
    ] if ids else []
    return [
        GateReply(
            _draft_text(saved, composed.draft, names, []),
            _buttons(work.id, work.audience, len(ids)),
        )
    ]
