"""Проверочные работы. Эталон проверяет код, в уведомление билет не кладётся."""

from datetime import UTC, datetime

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
    Attempt,
    ClassSubjectTeacher,
    ClassTeacher,
    Enrollment,
    LearningSession,
    SchoolClass,
    Subject,
    Topic,
    User,
    Work,
    WorkAnswer,
    WorkItem,
    WorkRecipient,
    WorkResource,
)
from app.domain.answers import answers_match
from app.domain.curriculum import fold_text, topic_by_title
from app.domain.drafts import build_check_draft, build_stimul_draft
from app.domain.onboarding import enqueue_notice
from app.domain.status import Thresholds


async def owned_class(session: AsyncSession, teacher: User, class_id: int | None) -> int | None:
    query = select(ClassTeacher.class_id).where(ClassTeacher.user_id == teacher.id)
    if class_id is not None:
        query = query.where(ClassTeacher.class_id == class_id)
    return await session.scalar(query.order_by(ClassTeacher.class_id))


async def classes_of(session: AsyncSession, teacher: User) -> list[dict]:
    class_ids = list(
        await session.scalars(
            select(ClassTeacher.class_id)
            .where(ClassTeacher.user_id == teacher.id)
            .order_by(ClassTeacher.class_id)
        )
    )
    items = []
    for class_id in class_ids:
        school_class = await session.get(SchoolClass, class_id)
        if school_class is None:
            continue
        subjects = (
            await session.execute(
                select(Subject.id, Subject.title)
                .join(ClassSubjectTeacher, ClassSubjectTeacher.subject_id == Subject.id)
                .where(
                    ClassSubjectTeacher.class_id == class_id,
                    ClassSubjectTeacher.user_id == teacher.id,
                )
                .order_by(Subject.title)
            )
        ).all()
        items.append(
            {
                "id": school_class.id,
                "title": school_class.title,
                "subjects": [{"id": row.id, "title": row.title} for row in subjects],
            }
        )
    return items


async def save_work(
    session: AsyncSession,
    teacher: User,
    *,
    class_id: int | None,
    topic: str,
    goal: str,
    count: int,
    difficulty: str,
    audience: str,
    students: list[str],
    student_ids: list[int] | None,
    prompts: list[str] | None,
    due_at: datetime | None,
    work_id: int | None = None,
    own_items: list[tuple[str, str]] | None = None,
    blurb: str = "",
    subject_id: int | None = None,
) -> tuple[dict | None, str | None, int]:
    current = await owned_class(session, teacher, class_id)
    if current is None:
        return None, "Нет доступа к классу", 403
    topic_row, topic_error = await _topic_for_teacher(
        session, teacher, current, topic, blurb, subject_id
    )
    if topic_error or topic_row is None:
        status = 422 if topic_error == "Напишите тему" else 403
        return None, topic_error or "Тему не удалось записать", status
    roster = await _active_students(session, current)
    if audience == "class":
        picked_ids = [user_id for user_id, _name in roster]
        picked = [name for _user_id, name in roster]
    else:
        resolved, resolve_error = _pick_students(roster, students, student_ids or [])
        if resolve_error or resolved is None:
            return None, resolve_error or "Выберите учеников этого класса", 422
        picked_ids, picked = resolved
    if own_items is not None:
        if not own_items:
            return None, "Нужно хотя бы одно задание", 422
        built = []
        for prompt, expected in own_items[:6]:
            question = prompt.strip()
            answer = expected.strip()
            if not question or not answer:
                return None, "У каждого задания нужны текст и верный ответ", 422
            built.append((question[:500], answer[:64]))
    else:
        draft = build_check_draft(topic_row.title, goal, count, difficulty, audience, picked)
        if draft is None:
            draft = build_stimul_draft(topic_row.title, goal, count, difficulty, audience, picked)
        if draft is None:
            return None, "По этой теме задания сам не соберу. Напишите вопросы и верные ответы.", 409
        bank_answers = {item["reference"] for item in draft["items"]}
        built = []
        for index, item in enumerate(draft["items"]):
            prompt = item["prompt"]
            if prompts is not None:
                if index >= len(prompts) or not prompts[index].strip():
                    return None, "Заполните текст каждого задания", 422
                prompt = prompts[index].strip()
            if item["reference"] not in bank_answers:
                return None, "Верный ответ не из собранных заданий", 422
            built.append((prompt[:500], item["reference"][:64]))
    now = datetime.now(UTC)
    if work_id is None:
        work = Work(
            class_id=current,
            subject_id=topic_row.subject_id,
            topic_id=topic_row.id,
            author_id=teacher.id,
            title=topic_row.title[:200],
            goal=goal.strip()[:300],
            difficulty=difficulty,
            status="draft",
            audience=audience,
            due_at=due_at,
            created_at=now,
        )
        session.add(work)
        await session.flush()
    else:
        work = await session.get(Work, work_id)
        if work is None or work.author_id != teacher.id or work.class_id != current:
            return None, "Черновик не найден", 404
        if work.status != "draft":
            return None, "Опубликованную работу уже не меняю", 409
        work.topic_id = topic_row.id
        work.subject_id = topic_row.subject_id
        work.title = topic_row.title[:200]
        work.goal = goal.strip()[:300]
        work.difficulty = difficulty
        work.audience = audience
        work.due_at = due_at
        old = list(await session.scalars(select(WorkItem).where(WorkItem.work_id == work.id)))
        for row in old:
            await session.delete(row)
        await session.flush()
    for position, (prompt, expected) in enumerate(built, start=1):
        session.add(WorkItem(work_id=work.id, position=position, prompt=prompt, expected=expected))
    old_recipients = list(
        await session.scalars(select(WorkRecipient).where(WorkRecipient.work_id == work.id))
    )
    for row in old_recipients:
        await session.delete(row)
    if audience == "selected":
        for user_id in picked_ids:
            session.add(WorkRecipient(work_id=work.id, user_id=user_id, status="draft"))
    await session.flush()
    return await _teacher_work(session, work, include_expected=True), None, 200


async def publish_work(session: AsyncSession, teacher: User, work_id: int) -> tuple[dict | None, str | None, int]:
    work = await session.get(Work, work_id)
    if work is None or work.author_id != teacher.id:
        return None, "Черновик не найден", 404
    if await owned_class(session, teacher, work.class_id) is None:
        return None, "Нет доступа к классу", 403
    if work.status == "published":
        return None, "Работа уже опубликована", 409
    recipients = await _activate_recipients(session, work)
    if not recipients:
        return None, "В классе нет учеников, которым можно отправить работу", 409
    now = datetime.now(UTC)
    work.status = "published"
    work.published_at = now
    subject = await session.get(Subject, work.subject_id)
    subject_title = subject.title if subject is not None else ""
    for user_id in recipients:
        await enqueue_notice(
            session,
            user_id,
            kind="work",
            title=work.title,
            body=f"Новое задание: {work.title}. {subject_title}. {work.goal}"[:500],
            button_text="Открыть задание",
            button_payload=f"open_work:{work.id}",
            ref_id=work.id,
        )
    await session.flush()
    payload = await _teacher_work(session, work, include_expected=True)
    payload["persisted"] = True
    payload["recipients"] = len(recipients)
    return payload, None, 200


async def list_teacher_works(session: AsyncSession, teacher: User, class_id: int | None) -> list[dict]:
    current = await owned_class(session, teacher, class_id)
    if current is None:
        return []
    rows = list(
        await session.scalars(
            select(Work)
            .where(Work.class_id == current, Work.author_id == teacher.id)
            .order_by(Work.id.desc())
        )
    )
    return [await _teacher_work(session, work, include_expected=False) for work in rows]


async def list_student_works(session: AsyncSession, student: User) -> list[dict]:
    rows = (
        await session.execute(
            select(Work, WorkRecipient, Subject, User)
            .join(WorkRecipient, WorkRecipient.work_id == Work.id)
            .join(Subject, Subject.id == Work.subject_id)
            .join(User, User.id == Work.author_id)
            .where(
                WorkRecipient.user_id == student.id,
                Work.status == "published",
                exists().where(ClassTeacher.class_id == Work.class_id),
            )
            .order_by(Work.id.desc())
        )
    ).all()
    items = []
    for work, recipient, subject, author in rows:
        questions = list(
            await session.scalars(
                select(WorkItem).where(WorkItem.work_id == work.id).order_by(WorkItem.position)
            )
        )
        answers = {
            row.item_id: row
            for row in await session.scalars(
                select(WorkAnswer).where(
                    WorkAnswer.work_id == work.id,
                    WorkAnswer.user_id == student.id,
                )
            )
        }
        resources = list(
            await session.scalars(
                select(WorkResource)
                .where(WorkResource.work_id == work.id)
                .order_by(WorkResource.id)
            )
        )
        items.append(
            {
                "id": work.id,
                "title": work.title,
                "goal": work.goal,
                "subject": subject.title,
                "topic": work.title,
                "author": author.display_name,
                "study": await _study_text(session, work),
                "status": recipient.status,
                "resources": [_resource_dict(row, work.id) for row in resources],
                "due_at": work.due_at.isoformat() if work.due_at else None,
                "items": [
                    {
                        "id": question.id,
                        "position": question.position,
                        "prompt": question.prompt,
                        "answered": question.id in answers,
                        "correct": answers[question.id].correct if question.id in answers else None,
                    }
                    for question in questions
                ],
            }
        )
    return items


async def submit_work(
    session: AsyncSession,
    student: User,
    work_id: int,
    answers: list[tuple[int, str]],
    settings: Settings,
) -> tuple[dict | None, str | None, int]:
    work = await session.get(Work, work_id)
    recipient = await session.scalar(
        select(WorkRecipient).where(
            WorkRecipient.work_id == work_id,
            WorkRecipient.user_id == student.id,
            WorkRecipient.status.in_(("assigned", "done")),
        )
    )
    if work is None or work.status != "published" or recipient is None:
        return None, "Этого задания нет", 404
    if not await class_has_teacher(session, work.class_id):
        return None, "В этом классе нет учителя, заданий нет", 404
    enrolled = await session.scalar(
        select(Enrollment.user_id).where(
            Enrollment.class_id == work.class_id,
            Enrollment.user_id == student.id,
            Enrollment.status == "active",
        )
    )
    if enrolled is None:
        return None, "Этого задания нет", 404
    if recipient.status == "done":
        stored = list(
            await session.scalars(
                select(WorkAnswer).where(
                    WorkAnswer.work_id == work.id,
                    WorkAnswer.user_id == student.id,
                )
            )
        )
        return {
            "ok": True,
            "persisted": True,
            "items": [{"id": row.item_id, "correct": row.correct} for row in stored],
            "status": "done",
        }, None, 200
    questions = {
        row.id: row
        for row in await session.scalars(select(WorkItem).where(WorkItem.work_id == work.id))
    }
    folded: dict[int, str] = {}
    for item_id, text in answers:
        folded[item_id] = text
    answers = list(folded.items())
    if not answers or any(item_id not in questions for item_id, _text in answers):
        return None, "Нужен ответ на задание этой работы", 422
    now = datetime.now(UTC)
    lesson: LearningSession | None = None
    checked = []
    for item_id, text in answers:
        question = questions[item_id]
        given = text.strip()[:200]
        if not given:
            return None, "Введите ответ", 422
        correct = answers_match(question.expected, given)
        feedback = "Верно." if correct else "Пока не сходится."
        existing = await session.scalar(
            select(WorkAnswer).where(WorkAnswer.item_id == item_id, WorkAnswer.user_id == student.id)
        )
        if existing is None:
            if lesson is None:
                lesson = LearningSession(
                    user_id=student.id,
                    mode="submission",
                    topic_id=work.topic_id,
                    step="done",
                    created_at=now,
                )
                session.add(lesson)
                await session.flush()
            session.add(
                WorkAnswer(
                    work_id=work.id,
                    item_id=item_id,
                    user_id=student.id,
                    answer=given,
                    correct=correct,
                    created_at=now,
                )
            )
            session.add(
                Attempt(
                    user_id=student.id,
                    topic_id=work.topic_id,
                    session_id=lesson.id,
                    mode="submission",
                    prompt=question.prompt[:500],
                    expected=question.expected[:64],
                    answer=given,
                    correct=correct,
                    hinted=False,
                    feedback=feedback,
                    created_at=now,
                )
            )
        else:
            existing.answer = given
            existing.correct = correct
            existing.created_at = now
            attempt = await session.scalar(
                select(Attempt)
                .where(
                    Attempt.user_id == student.id,
                    Attempt.mode == "submission",
                    Attempt.topic_id == work.topic_id,
                    Attempt.prompt == question.prompt[:500],
                )
                .order_by(Attempt.id.desc())
            )
            if attempt is not None:
                attempt.answer = given
                attempt.correct = correct
                attempt.expected = question.expected[:64]
                attempt.feedback = feedback
        checked.append({"id": item_id, "correct": correct})
    await session.flush()
    from app.bot.service import _recompute, _today

    await _recompute(
        session,
        student.id,
        work.topic_id,
        _today(settings),
        Thresholds(settings.status_repeat_below, settings.status_mastered_from),
    )
    stored = await session.scalar(
        select(func.count()).select_from(WorkAnswer).where(
            WorkAnswer.work_id == work.id,
            WorkAnswer.user_id == student.id,
        )
    )
    if int(stored or 0) >= len(questions):
        recipient.status = "done"
    await session.flush()
    return {"ok": True, "persisted": True, "items": checked, "status": recipient.status}, None, 200


async def work_results(session: AsyncSession, teacher: User, work_id: int) -> tuple[dict | None, str | None, int]:
    work = await session.get(Work, work_id)
    if work is None or work.author_id != teacher.id:
        return None, "Работы нет", 404
    if await owned_class(session, teacher, work.class_id) is None:
        return None, "Нет доступа к классу", 403
    payload = await _teacher_work(session, work, include_expected=False)
    payload["people"] = await _result_people(session, work)
    return payload, None, 200


async def student_assignment_note(session: AsyncSession, student: User) -> str:
    class_id = await session.scalar(
        select(Enrollment.class_id).where(
            Enrollment.user_id == student.id,
            Enrollment.status == "active",
        )
    )
    if class_id is None:
        return ""
    if not await class_has_teacher(session, class_id):
        return "no_teacher"
    return ""


def _resource_dict(row: WorkResource, work_id: int) -> dict:
    if row.kind == "link":
        url = row.url or ""
    else:
        url = f"/api/student/works/{work_id}/resources/{row.id}/file"
    return {
        "id": row.id,
        "kind": row.kind,
        "title": row.title,
        "url": url,
        "mime": row.mime,
        "size": row.size,
    }


async def attach_resource(
    session: AsyncSession,
    teacher: User,
    work_id: int,
    *,
    title: str,
    url: str | None,
    file_name: str,
    mime: str,
    blob: bytes | None,
) -> tuple[dict | None, str | None, int]:
    """Файл или ссылка к черновику работы. После публикации уже не меняется."""
    work = await session.get(Work, work_id)
    if work is None or work.author_id != teacher.id:
        return None, "Работы нет", 404
    if await owned_class(session, teacher, work.class_id) is None:
        return None, "Нет доступа к классу", 403
    if work.status != "draft":
        return None, "Опубликованную работу уже не меняю", 409
    cleaned = " ".join(title.split()).strip()[:200]
    if blob is not None:
        if not blob:
            return None, "Файл пустой", 422
        if len(blob) > 15 * 1024 * 1024:
            return None, "Файл больше 15 МБ", 413
        kind = "file"
        link = None
        safe_mime = (mime or "application/octet-stream").strip()[:100] or "application/octet-stream"
        safe_name = (file_name or "material").strip()[:200] or "material"
        size = len(blob)
        label = cleaned or safe_name.rsplit(".", 1)[0] or safe_name
    else:
        link = (url or "").strip()[:1000]
        if not link.startswith(("https://", "http://")):
            return None, "Нужна ссылка http:// или https://", 422
        if not cleaned:
            return None, "Напишите название материала", 422
        kind = "link"
        safe_mime = "text/uri-list"
        safe_name = ""
        size = len(link)
        label = cleaned
    now = datetime.now(UTC)
    row = WorkResource(
        work_id=work.id,
        kind=kind,
        title=label[:200],
        url=link,
        mime=safe_mime,
        blob=blob,
        size=size,
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return {"id": row.id, "kind": kind, "title": row.title, "url": row.url or ""}, None, 200


async def detach_resource(
    session: AsyncSession, teacher: User, work_id: int, resource_id: int
) -> tuple[bool, str | None, int]:
    work = await session.get(Work, work_id)
    if work is None or work.author_id != teacher.id:
        return False, "Работы нет", 404
    if await owned_class(session, teacher, work.class_id) is None:
        return False, "Нет доступа к классу", 403
    if work.status != "draft":
        return False, "Опубликованную работу уже не меняю", 409
    row = await session.get(WorkResource, resource_id)
    if row is None or row.work_id != work.id:
        return False, "Материала нет", 404
    await session.delete(row)
    await session.flush()
    return True, None, 200


async def student_resource_file(
    session: AsyncSession, student: User, work_id: int, resource_id: int
) -> tuple[WorkResource | None, str | None, int]:
    work = await session.get(Work, work_id)
    recipient = await session.scalar(
        select(WorkRecipient).where(
            WorkRecipient.work_id == work_id,
            WorkRecipient.user_id == student.id,
            WorkRecipient.status.in_(("assigned", "done")),
        )
    )
    if work is None or work.status != "published" or recipient is None:
        return None, "Материала нет", 404
    row = await session.get(WorkResource, resource_id)
    if row is None or row.work_id != work.id or row.kind != "file" or row.blob is None:
        return None, "Материала нет", 404
    return row, None, 200


async def class_has_teacher(session: AsyncSession, class_id: int) -> bool:
    found = await session.scalar(
        select(ClassTeacher.user_id).where(ClassTeacher.class_id == class_id)
    )
    return found is not None


async def _active_students(session: AsyncSession, class_id: int) -> list[tuple[int, str]]:
    rows = (
        await session.execute(
            select(User.id, User.display_name)
            .join(Enrollment, Enrollment.user_id == User.id)
            .where(
                Enrollment.class_id == class_id,
                Enrollment.status == "active",
                User.role == "student",
                User.deleted_at.is_(None),
            )
            .order_by(User.id)
        )
    ).all()
    return [(row.id, row.display_name) for row in rows]


def _pick_students(
    roster: list[tuple[int, str]],
    names: list[str],
    student_ids: list[int],
) -> tuple[tuple[list[int], list[str]] | None, str | None]:
    by_id = {user_id: name for user_id, name in roster}
    if student_ids:
        picked_ids: list[int] = []
        for user_id in student_ids:
            if user_id not in by_id or user_id in picked_ids:
                return None, "Выберите учеников этого класса"
            picked_ids.append(user_id)
        return (picked_ids, [by_id[user_id] for user_id in picked_ids]), None
    counts: dict[str, int] = {}
    for _user_id, name in roster:
        counts[name] = counts.get(name, 0) + 1
    picked_names: list[str] = []
    for name in names:
        cleaned = name.strip()
        if cleaned not in counts or cleaned in picked_names:
            return None, "Выберите учеников этого класса"
        if counts[cleaned] > 1:
            return None, "В классе есть одинаковые имена. Отметьте учеников в списке."
        picked_names.append(cleaned)
    if not picked_names:
        return None, "Выберите учеников этого класса"
    ordered = list(picked_names)
    id_by_name = {name: user_id for user_id, name in roster}
    return ([id_by_name[name] for name in ordered], ordered), None


async def _activate_recipients(session: AsyncSession, work: Work) -> list[int]:
    if work.audience == "selected":
        rows = list(
            await session.scalars(
                select(WorkRecipient).where(
                    WorkRecipient.work_id == work.id,
                    WorkRecipient.status == "draft",
                )
            )
        )
        for row in rows:
            row.status = "assigned"
        return [row.user_id for row in rows]
    rows = (
        await session.execute(
            select(User.id)
            .join(Enrollment, Enrollment.user_id == User.id)
            .where(
                Enrollment.class_id == work.class_id,
                Enrollment.status == "active",
                User.role == "student",
                User.deleted_at.is_(None),
            )
            .order_by(User.id)
        )
    ).all()
    ids = []
    for row in rows:
        ids.append(row.id)
        session.add(WorkRecipient(work_id=work.id, user_id=row.id, status="assigned"))
    return ids


async def _teacher_work(session: AsyncSession, work: Work, *, include_expected: bool) -> dict:
    questions = list(
        await session.scalars(
            select(WorkItem).where(WorkItem.work_id == work.id).order_by(WorkItem.position)
        )
    )
    recipient_rows, handed, started = await _sync_recipients(session, work, questions)
    done = sum(1 for row in recipient_rows if row.status == "done")
    subject = await session.get(Subject, work.subject_id)
    topic = await session.get(Topic, work.topic_id)
    return {
        "id": work.id,
        "title": work.title,
        "goal": work.goal,
        "status": work.status,
        "difficulty": work.difficulty,
        "audience": work.audience,
        "subject": subject.title if subject else "",
        "topic": topic.title if topic else work.title,
        "due_at": work.due_at.isoformat() if work.due_at else None,
        "created_at": work.created_at.isoformat(),
        "published_at": work.published_at.isoformat() if work.published_at else None,
        "recipients": len(recipient_rows),
        "done": done,
        "handed": handed,
        "started": started,
        "persisted": True,
        "items": [
            {
                "id": question.id,
                "position": question.position,
                "prompt": question.prompt,
                **({"reference": question.expected} if include_expected else {}),
            }
            for question in questions
        ],
    }


async def _result_people(session: AsyncSession, work: Work) -> list[dict]:
    rows = (
        await session.execute(
            select(User, WorkRecipient)
            .join(WorkRecipient, WorkRecipient.user_id == User.id)
            .where(WorkRecipient.work_id == work.id)
            .order_by(User.display_name)
        )
    ).all()
    people = []
    for person, recipient in rows:
        answers = list(
            await session.scalars(
                select(WorkAnswer).where(
                    WorkAnswer.work_id == work.id,
                    WorkAnswer.user_id == person.id,
                )
            )
        )
        correct = sum(1 for row in answers if row.correct)
        people.append(
            {
                "user_id": person.id,
                "display_name": person.display_name,
                "status": recipient.status,
                "answered": len(answers),
                "correct": correct,
            }
        )
    return people


def topic_material_ok(title: str) -> bool:
    return topic_by_title(title) is not None


async def _appointed_subject(session: AsyncSession, teacher: User, class_id: int) -> int | None:
    return await session.scalar(
        select(ClassSubjectTeacher.subject_id)
        .where(
            ClassSubjectTeacher.class_id == class_id,
            ClassSubjectTeacher.user_id == teacher.id,
        )
        .order_by(ClassSubjectTeacher.subject_id)
    )


async def _subject_for_teacher(
    session: AsyncSession, teacher: User, class_id: int, subject_id: int | None
) -> int | None:
    """Выбранный предмет, если учитель назначен на него в этом классе. Иначе первый."""
    if subject_id is None:
        return await _appointed_subject(session, teacher, class_id)
    post = await session.scalar(
        select(ClassSubjectTeacher.subject_id).where(
            ClassSubjectTeacher.class_id == class_id,
            ClassSubjectTeacher.user_id == teacher.id,
            ClassSubjectTeacher.subject_id == subject_id,
        )
    )
    return post


async def ensure_subject(
    session: AsyncSession, teacher: User, class_id: int, title: str
) -> tuple[Subject, bool]:
    """Предмет из справочника + назначение учителя в классе. Создаёт при отсутствии."""
    cleaned = " ".join(title.split()).strip()[:200]
    subject = await session.scalar(select(Subject).where(Subject.title == cleaned))
    created = subject is None
    if subject is None:
        subject = Subject(title=cleaned)
        session.add(subject)
        await session.flush()
    post = await session.scalar(
        select(ClassSubjectTeacher.subject_id).where(
            ClassSubjectTeacher.class_id == class_id,
            ClassSubjectTeacher.user_id == teacher.id,
            ClassSubjectTeacher.subject_id == subject.id,
        )
    )
    if post is None:
        session.add(
            ClassSubjectTeacher(
                class_id=class_id, user_id=teacher.id, subject_id=subject.id
            )
        )
        await session.flush()
    return subject, created


async def upsert_topic(
    session: AsyncSession, subject_id: int, title: str, blurb: str = ""
) -> tuple[Topic, bool]:
    """Тема предмета: находит по fold-тексту или создаёт следующей по position."""
    cleaned = " ".join(title.split()).strip()[:200]
    rows = list(await session.scalars(select(Topic).where(Topic.subject_id == subject_id)))
    folded = fold_text(cleaned)
    found = next((row for row in rows if fold_text(row.title) == folded), None)
    created = found is None
    if found is None:
        position = await session.scalar(
            select(func.max(Topic.position)).where(Topic.subject_id == subject_id)
        )
        found = Topic(
            subject_id=subject_id,
            title=cleaned,
            position=int(position or 0) + 1,
            blurb="",
        )
        session.add(found)
        await session.flush()
    note = " ".join(blurb.split()).strip()[:800]
    if note:
        found.blurb = note
    return found, created


async def program_of(
    session: AsyncSession, teacher: User, class_id: int
) -> tuple[list[dict], list[dict]]:
    """Предметы учителя в классе и темы этих предметов — для конструктора."""
    subject_ids = list(
        await session.scalars(
            select(ClassSubjectTeacher.subject_id)
            .where(
                ClassSubjectTeacher.class_id == class_id,
                ClassSubjectTeacher.user_id == teacher.id,
            )
            .order_by(ClassSubjectTeacher.subject_id)
        )
    )
    if not subject_ids:
        return [], []
    subjects = []
    for subject_id in subject_ids:
        subject = await session.get(Subject, subject_id)
        if subject is not None:
            subjects.append({"id": subject.id, "title": subject.title})
    topic_rows = (
        await session.execute(
            select(Topic)
            .where(Topic.subject_id.in_(subject_ids))
            .order_by(Topic.subject_id, Topic.position)
        )
    ).scalars().all()
    topics = [
        {
            "id": topic.id,
            "subject_id": topic.subject_id,
            "title": topic.title,
            "blurb": topic.blurb,
            "position": topic.position,
        }
        for topic in topic_rows
    ]
    return subjects, topics


async def _topic_for_teacher(
    session: AsyncSession,
    teacher: User,
    class_id: int,
    title: str,
    blurb: str,
    subject_id: int | None = None,
) -> tuple[Topic | None, str | None]:
    cleaned = " ".join(title.split()).strip()[:200]
    if len(cleaned) < 2:
        return None, "Напишите тему"
    resolved = await _subject_for_teacher(session, teacher, class_id, subject_id)
    if resolved is None:
        return None, "Нет назначения на этот предмет"
    subject_id = resolved
    rows = list(await session.scalars(select(Topic).where(Topic.subject_id == subject_id)))
    folded = fold_text(cleaned)
    found = next((row for row in rows if fold_text(row.title) == folded), None)
    if found is None:
        position = await session.scalar(
            select(func.max(Topic.position)).where(Topic.subject_id == subject_id)
        )
        found = Topic(
            subject_id=subject_id,
            title=cleaned,
            position=int(position or 0) + 1,
            blurb="",
        )
        session.add(found)
        await session.flush()
    note = " ".join(blurb.split()).strip()[:800]
    if note:
        found.blurb = note
    return found, None


async def _study_text(session: AsyncSession, work: Work) -> str:
    topic = await session.get(Topic, work.topic_id)
    material = topic_by_title(topic.title if topic is not None else work.title)
    if material is not None:
        return material.explanation
    if topic is not None and topic.blurb.strip():
        return topic.blurb.strip()
    return ""


async def _sync_recipients(
    session: AsyncSession,
    work: Work,
    questions: list[WorkItem],
) -> tuple[list[WorkRecipient], list[str], list[str]]:
    recipient_rows = list(
        await session.scalars(select(WorkRecipient).where(WorkRecipient.work_id == work.id))
    )
    answers = list(
        await session.scalars(select(WorkAnswer).where(WorkAnswer.work_id == work.id))
    )
    by_user: dict[int, set[int]] = {}
    for answer in answers:
        by_user.setdefault(answer.user_id, set()).add(answer.item_id)
    ids = [row.user_id for row in recipient_rows]
    names: dict[int, str] = {}
    if ids:
        people = (
            await session.execute(select(User.id, User.display_name).where(User.id.in_(ids)))
        ).all()
        names = {row.id: row.display_name for row in people}
    question_ids = {row.id for row in questions}
    changed = False
    for recipient in recipient_rows:
        got = by_user.get(recipient.user_id, set())
        if (
            recipient.status == "assigned"
            and question_ids
            and question_ids <= got
        ):
            recipient.status = "done"
            changed = True
    if changed:
        await session.flush()
        session.info["work_repaired"] = True
    handed = [
        names[row.user_id]
        for row in recipient_rows
        if row.status == "done" and row.user_id in names
    ]
    started = [
        names[row.user_id]
        for row in recipient_rows
        if row.status != "done" and by_user.get(row.user_id) and row.user_id in names
    ]
    return recipient_rows, handed, started
