import re
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, user_from_cookie
from app.bot.assist import clean_photo
from app.bot.compose import (
    ASSISTANT_OFF,
    NO_BANK,
    class_summary,
    classroom_context,
    compose_draft,
    pick_topic,
)
from app.bot.service import class_report
from app.db.models import (
    ClassSubjectTeacher,
    ClassTeacher,
    Enrollment,
    SchoolClass,
    Subject,
    Topic,
    User,
)
from app.domain import chats as chat_store
from app.domain.accounts import approve_enrollment, rotate_class_key, set_class_join
from app.domain.assist import match_students
from app.domain.images import image_kind
from app.domain.library import delete_material, list_materials, save_material
from app.domain.materials import extract_text, file_kind, normalize
from app.domain.onboarding import claims_for, reviewer_name
from app.domain.curriculum import fold_text
from app.domain.schoolwork import (
    classes_of,
    ensure_subject,
    list_teacher_works,
    owned_class,
    program_of,
    upsert_topic,
)

router = APIRouter()

MAX_PHOTO_BYTES = 8 * 1024 * 1024

DELIVERY_MISSING = (
    "Отправка работ в MAX ещё не подключена. Черновик не сохранён и ученикам не ушёл."
)


class DraftBody(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=300)
    count: int = Field(ge=1, le=6)
    difficulty: Literal["easy", "normal", "hard"]
    audience: Literal["class", "selected"]
    students: list[str] = Field(default_factory=list, max_length=40)
    use_material: bool = False
    subject_id: int | None = None
    class_id: int | None = None


async def _report(request: Request, session: AsyncSession, class_id: int | None = None):
    teacher = await user_from_cookie(request, session, "teacher")
    report = await class_report(session, teacher, request.app.state.settings, class_id)
    if report is None:
        raise HTTPException(status_code=403, detail="Нет доступа к классу")
    return report


def _students(report, body: DraftBody) -> list[str]:
    roster = [student.display_name for student in report.students]
    if body.audience == "class":
        return roster
    known = set(roster)
    wanted: list[str] = []
    for name in body.students:
        cleaned = name.strip()
        if len(cleaned) > 200 or cleaned not in known or cleaned in wanted:
            if cleaned not in known or len(cleaned) > 200:
                raise HTTPException(status_code=422, detail="Выберите учеников этого класса")
            continue
        wanted.append(cleaned)
    if not wanted:
        raise HTTPException(status_code=422, detail="Выберите учеников этого класса")
    return wanted


async def _prepare(request: Request, session: AsyncSession, report, body: DraftBody) -> dict:
    if not request.app.state.settings.feature_quiz:
        raise HTTPException(status_code=404, detail="Сборка проверок выключена")
    teacher = await user_from_cookie(request, session, "teacher")
    current = await owned_class(session, teacher, body.class_id)
    subject_title = ""
    if body.subject_id is not None:
        appointed = await session.scalar(
            select(ClassSubjectTeacher.subject_id).where(
                ClassSubjectTeacher.class_id == current,
                ClassSubjectTeacher.user_id == teacher.id,
                ClassSubjectTeacher.subject_id == body.subject_id,
            )
        )
        if appointed is None:
            raise HTTPException(status_code=403, detail="Нет назначения на этот предмет")
        found = await session.get(Subject, body.subject_id)
        subject_title = found.title if found else ""
    composed = await compose_draft(
        session,
        request.app.state.explainer,
        class_id=current,
        topic=body.topic,
        goal=body.goal,
        count=body.count,
        difficulty=body.difficulty,
        audience=body.audience,
        students=_students(report, body),
        use_material=body.use_material,
        subject=subject_title,
    )
    if composed.error or composed.draft is None:
        raise HTTPException(status_code=composed.status, detail=composed.error or NO_BANK)
    composed.draft["subject_id"] = body.subject_id
    return composed.draft


@router.get("/api/teacher/class")
async def teacher_class(
    request: Request,
    class_id: int | None = None,
    session: AsyncSession = Depends(db_session),
) -> dict:
    report = await _report(request, session, class_id)
    payload = report.as_dict()
    teacher = await user_from_cookie(request, session, "teacher")
    owned = select(ClassTeacher.class_id).where(ClassTeacher.user_id == teacher.id)
    if class_id is not None:
        owned = owned.where(ClassTeacher.class_id == class_id)
    current = await session.scalar(owned.order_by(ClassTeacher.class_id))
    school_class = await session.get(SchoolClass, current) if current is not None else None
    pending = []
    if current is not None:
        rows = await session.execute(
            select(User.id, User.display_name)
            .join(Enrollment, Enrollment.user_id == User.id)
            .where(Enrollment.class_id == current, Enrollment.status == "pending")
            .order_by(User.id)
        )
        pending = [{"id": row.id, "display_name": row.display_name} for row in rows]
    payload["class_id"] = current
    payload["pending_students"] = pending
    payload["join_open"] = bool(school_class.join_open) if school_class else False
    payload["join_key"] = school_class.join_key if school_class else ""
    payload["join_code"] = school_class.join_code if school_class else ""
    payload["classes"] = await classes_of(session, teacher)
    payload["can_manage_school"] = bool(teacher.can_manage_school)
    payload["claims_reviewer"] = await reviewer_name(session)
    payload["pending_claims"] = await claims_for(session, teacher)
    active_students = 0
    if current is not None:
        active_students = int(
            await session.scalar(
                select(func.count())
                .select_from(Enrollment)
                .where(Enrollment.class_id == current, Enrollment.status == "active")
            )
            or 0
        )
    teacher_count = int(
        await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "teacher", User.status == "active", User.deleted_at.is_(None))
        )
        or 0
    )
    payload["active_students"] = active_students
    payload["teacher_count"] = teacher_count
    subjects = []
    for item in payload["classes"]:
        if current is not None and item["id"] == current:
            subjects = item["subjects"]
    payload["subjects"] = subjects
    payload["subject_title"] = subjects[0]["title"] if subjects else ""
    return payload


@router.get("/api/teacher/assignments")
async def assignments(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    await _report(request, session)
    teacher = await user_from_cookie(request, session, "teacher")
    items = await list_teacher_works(session, teacher, None)
    if session.info.get("work_repaired"):
        await session.commit()
    return {
        "items": items,
        "delivery": "max" if items else "empty",
        "detail": "" if items else "Назначенных работ пока нет.",
    }


@router.post("/api/teacher/drafts")
async def drafts(
    body: DraftBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    report = await _report(request, session, body.class_id)
    return await _prepare(request, session, report, body)


@router.post("/api/teacher/assignments", status_code=501)
async def create_assignment(
    body: DraftBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> None:
    await _report(request, session, body.class_id)
    raise HTTPException(status_code=501, detail=DELIVERY_MISSING)


class AskBody(BaseModel):
    text: str = Field(min_length=2, max_length=1500)
    class_id: int | None = None


_TOPIC_ADD = re.compile(
    r"(?:добавь|создай|заведи|нужна)\s+(?:мне\s+)?тему\s+(.+)", re.IGNORECASE
)


def _parse_topic_add(text: str) -> tuple[str, str] | None:
    """«Добавь тему Квадратные уравнения по физике» → (тема, предмет)."""
    match = _TOPIC_ADD.search(text.strip())
    if not match:
        return None
    rest = match.group(1).strip(" .!?")
    topic, subject = rest, ""
    parts = re.split(r"\s+(?:по|для)\s+(.+)$", rest)
    if len(parts) == 2 and len(parts[0].strip()) >= 2:
        topic, subject = parts[0].strip(), parts[1].strip()
    if len(topic) < 2:
        return None
    return topic[:200], subject[:200]


async def _add_topic_reply(
    session: AsyncSession,
    teacher: User,
    class_id: int | None,
    parsed: tuple[str, str],
) -> dict:
    """«Добавь тему» — это структура программы, а не черновик проверки."""
    current = await owned_class(session, teacher, class_id)
    if current is None:
        return {"kind": "chat", "text": "Нет доступа к классу."}
    title, hint = parsed
    subjects, _topics = await program_of(session, teacher, current)
    subject = None
    if hint:
        wanted = fold_text(hint)
        subject = next(
            (
                item
                for item in subjects
                if wanted
                and (wanted in fold_text(item["title"]) or fold_text(item["title"]) in wanted)
            ),
            None,
        )
        if subject is None:
            created_subject, _made = await ensure_subject(session, teacher, current, hint)
            subject = {"id": created_subject.id, "title": created_subject.title}
    if subject is None:
        if len(subjects) == 1:
            subject = subjects[0]
        elif not subjects:
            return {
                "kind": "chat",
                "text": "Сначала назначьте предмет в классе, потом добавлю тему.",
            }
        else:
            names = ", ".join(f"«{item['title']}»" for item in subjects)
            return {
                "kind": "chat",
                "text": f"В какой предмет добавить тему «{title}»? У вас: {names}.",
            }
    topic, created = await upsert_topic(session, subject["id"], title)
    await session.commit()
    verb = "Добавил" if created else "Такая тема уже есть"
    return {
        "kind": "chat",
        "text": f"{verb} «{topic.title}» в предмете «{subject['title']}». Теперь по ней можно собирать проверку.",
        "refresh_program": True,
    }


_PROGRESS_WORDS = re.compile(
    r"справля|успева|прогресс|статистик|результат|успеваемост|оценк|успех|"
    r"кто\s+(?:слаб|лучше|худш|не\s+справ)|насколько|как\s+(?:дела|справ|идут)|"
    r"сдали|решили",
    re.IGNORECASE,
)
_WORK_VERBS = re.compile(
    r"собери|сделай|создай|подготовь|проверь|провер|задач|тест|домашн|карточк|"
    r"вопрос|задани|практик|экзамен|контрольн",
    re.IGNORECASE,
)


def _progress_question(text: str) -> bool:
    """Вопрос про успеваемость класса, а не просьба собрать проверку."""
    return bool(_PROGRESS_WORDS.search(text)) and not _WORK_VERBS.search(text)


async def _summary_answer(
    tutor,
    report,
    text: str,
    history: list[dict] | None,
    context: str,
) -> dict:
    """Вопросы об успеваемости: модель отвечает по данным класса.
    Кодовая сводка идёт как факты в контекст, а не как готовый шаблон."""
    if tutor.enabled:
        grounded = (
            f"{context}\n\nСводка по темам (посчитана кодом):\n{class_summary(report)}"
        )
        reply = await tutor.teacher_reply(text, history, grounded)
        if reply:
            return {"kind": "summary", "text": reply}
    return {"kind": "summary", "text": class_summary(report)}


async def _assistant_answer(
    request: Request,
    session: AsyncSession,
    report,
    teacher: User,
    text: str,
    class_id: int | None,
    history: list[dict] | None = None,
) -> dict:
    """Ответ помощника на просьбу учителя. Работу не отправляет: черновик на проверку."""
    parsed = _parse_topic_add(text)
    if parsed is not None:
        return await _add_topic_reply(session, teacher, class_id, parsed)
    tutor = request.app.state.explainer
    if not tutor.enabled:
        raise HTTPException(status_code=503, detail=ASSISTANT_OFF)
    titles = [topic.title for topic in report.topics]
    context = await classroom_context(session, teacher, class_id, report)
    ask = await tutor.read_teacher(text, titles, history, context)
    if ask is None:
        raise HTTPException(status_code=503, detail=ASSISTANT_OFF)
    if ask.intent == "summary":
        return await _summary_answer(tutor, report, text, history, context)
    if ask.intent in {"chat", "other"}:
        reply = ask.reply or (
            await tutor.teacher_reply(text, history, context) if tutor.enabled else ""
        )
        return {
            "kind": "chat",
            "text": reply
            or "Могу собрать проверку по теме, показать слабые места класса "
            "или ответить на вопрос о работе.",
        }
    if ask.intent == "work" and _progress_question(text):
        return await _summary_answer(tutor, report, text, history, context)
    class_id = await owned_class(session, teacher, class_id)
    topic = await pick_topic(session, tutor, report, ask, class_id=class_id)
    if ask.intent != "work" or not topic:
        return {
            "kind": "help",
            "text": "Напишите тему и что проверить, например: «Дроби, сложение с разными знаменателями, 4 задания».",
        }
    roster = [(student.user_id, student.display_name) for student in report.students]
    ids, names, unknown = match_students(list(ask.students), roster)
    audience = "selected" if ids else "class"
    topic_subject = next(
        (item.subject_id for item in report.topics if item.title == topic), None
    )
    subject_title = ""
    if topic_subject is not None:
        found = await session.get(Subject, topic_subject)
        subject_title = found.title if found else ""
    composed = await compose_draft(
        session,
        tutor,
        class_id=class_id,
        topic=topic,
        goal=ask.goal or topic,
        count=ask.count,
        difficulty=ask.difficulty,
        audience=audience,
        students=names if ids else [name for _id, name in roster],
        use_material=ask.use_material,
        subject=subject_title,
    )
    if composed.error or composed.draft is None:
        raise HTTPException(status_code=composed.status, detail=composed.error or NO_BANK)
    topic_subject = next(
        (item.subject_id for item in report.topics if item.title == topic), None
    )
    return {
        "kind": "draft",
        "draft": composed.draft,
        "wizard": {
            "topic": topic,
            "goal": ask.goal or topic,
            "count": composed.draft["count"],
            "difficulty": ask.difficulty,
            "audience": audience,
            "student_ids": ids,
            "students": names,
            "use_material": ask.use_material,
            "subject_id": topic_subject,
        },
        "unknown_students": unknown,
    }


@router.post("/api/teacher/assistant")
async def assistant(
    body: AskBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    report = await _report(request, session, body.class_id)
    teacher = await user_from_cookie(request, session, "teacher")
    return await _assistant_answer(
        request, session, report, teacher, body.text, body.class_id
    )


@router.get("/api/teacher/materials")
async def materials(
    request: Request,
    class_id: int | None = None,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    current = await owned_class(session, teacher, class_id)
    if current is None:
        raise HTTPException(status_code=403, detail="Нет доступа к классу")
    return {"items": await list_materials(session, current)}


@router.post("/api/teacher/materials")
async def upload_material(
    request: Request,
    file: UploadFile = File(),
    title: str = Form(""),
    class_id: int | None = Form(None),
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    current = await owned_class(session, teacher, class_id)
    if current is None:
        await file.close()
        raise HTTPException(status_code=403, detail="Нет доступа к классу")
    settings = request.app.state.settings
    limit = settings.material_max_mb * 1024 * 1024
    blob = await file.read(limit + 1)
    await file.close()
    if len(blob) > limit:
        raise HTTPException(status_code=413, detail=f"Файл больше {settings.material_max_mb} МБ")
    name = file.filename or "material"
    if image_kind(blob) is not None:
        tutor = request.app.state.explainer
        if not tutor.enabled:
            raise HTTPException(status_code=503, detail="Фото страниц сейчас не распознать. Загрузите PDF или DOCX.")
        image = clean_photo(blob)
        text = normalize(await tutor.read_photo(*image) or "") if image else ""
        if len(text) < 40:
            raise HTTPException(status_code=422, detail="Текст на фото не прочитался. Сфотографируйте страницу ровнее.")
        kind = "photo"
    else:
        extracted = extract_text(name, blob)
        if extracted.error:
            raise HTTPException(status_code=422, detail=extracted.error)
        text, kind = extracted.text, file_kind(name, blob) or "text"
    material = await save_material(
        session,
        class_id=current,
        author_id=teacher.id,
        title=title.strip() or name.rsplit(".", 1)[0],
        kind=kind,
        text=text,
    )
    await session.commit()
    items = await list_materials(session, current)
    return {"item": next(item for item in items if item["id"] == material.id), "items": items}


@router.delete("/api/teacher/materials/{material_id}")
async def remove_material(
    material_id: int,
    request: Request,
    class_id: int | None = None,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    current = await owned_class(session, teacher, class_id)
    if current is None or not await delete_material(session, current, material_id):
        raise HTTPException(status_code=404, detail="Материала нет")
    await session.commit()
    return {"ok": True}


@router.get("/api/teacher/program")
async def program(
    request: Request,
    class_id: int | None = None,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    current = await owned_class(session, teacher, class_id)
    if current is None:
        raise HTTPException(status_code=403, detail="Нет доступа к классу")
    subjects, topics = await program_of(session, teacher, current)
    return {"subjects": subjects, "topics": topics, "class_id": current}


class SubjectBody(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    class_id: int | None = None


@router.post("/api/teacher/subjects")
async def create_subject(
    body: SubjectBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    current = await owned_class(session, teacher, body.class_id)
    if current is None:
        raise HTTPException(status_code=403, detail="Нет доступа к классу")
    title = " ".join(body.title.split()).strip()[:200]
    subject = await session.scalar(select(Subject).where(Subject.title == title))
    created = subject is None
    if subject is None:
        subject = Subject(title=title)
        session.add(subject)
        await session.flush()
    post = await session.scalar(
        select(ClassSubjectTeacher.subject_id).where(
            ClassSubjectTeacher.class_id == current,
            ClassSubjectTeacher.user_id == teacher.id,
            ClassSubjectTeacher.subject_id == subject.id,
        )
    )
    if post is None:
        session.add(
            ClassSubjectTeacher(
                class_id=current, user_id=teacher.id, subject_id=subject.id
            )
        )
        await session.flush()
    await session.commit()
    return {"id": subject.id, "title": subject.title, "created": created}


class TopicBody(BaseModel):
    subject_id: int
    title: str = Field(min_length=2, max_length=200)
    blurb: str = Field(default="", max_length=800)
    class_id: int | None = None


@router.post("/api/teacher/topics")
async def create_topic(
    body: TopicBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    current = await owned_class(session, teacher, body.class_id)
    if current is None:
        raise HTTPException(status_code=403, detail="Нет доступа к классу")
    post = await session.scalar(
        select(ClassSubjectTeacher.subject_id).where(
            ClassSubjectTeacher.class_id == current,
            ClassSubjectTeacher.user_id == teacher.id,
            ClassSubjectTeacher.subject_id == body.subject_id,
        )
    )
    if post is None:
        raise HTTPException(status_code=403, detail="Нет назначения на этот предмет")
    from app.domain.curriculum import fold_text

    title = " ".join(body.title.split()).strip()[:200]
    rows = list(
        await session.scalars(select(Topic).where(Topic.subject_id == body.subject_id))
    )
    folded = fold_text(title)
    found = next((row for row in rows if fold_text(row.title) == folded), None)
    if found is None:
        position = await session.scalar(
            select(func.max(Topic.position)).where(Topic.subject_id == body.subject_id)
        )
        found = Topic(
            subject_id=body.subject_id,
            title=title,
            position=int(position or 0) + 1,
            blurb="",
        )
        session.add(found)
        await session.flush()
    note = " ".join(body.blurb.split()).strip()[:800]
    if note:
        found.blurb = note
    await session.commit()
    return {
        "id": found.id,
        "subject_id": found.subject_id,
        "title": found.title,
        "blurb": found.blurb,
        "position": found.position,
    }


class KeyBody(BaseModel):
    action: Literal["rotate", "disable", "enable"]


@router.post("/api/teacher/joins/{student_id}/approve")
async def approve_join(
    student_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict[str, bool]:
    teacher = await user_from_cookie(request, session, "teacher")
    ok = await approve_enrollment(session, teacher.id, student_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Заявки нет")
    await session.commit()
    return {"ok": True}


@router.post("/api/teacher/class/key")
async def class_key(
    body: KeyBody,
    request: Request,
    class_id: int | None = None,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    owned = select(ClassTeacher.class_id).where(ClassTeacher.user_id == teacher.id)
    if class_id is not None:
        owned = owned.where(ClassTeacher.class_id == class_id)
    current = await session.scalar(owned.order_by(ClassTeacher.class_id))
    if current is None:
        raise HTTPException(status_code=403, detail="Нет доступа к классу")
    if body.action == "rotate":
        school_class = await rotate_class_key(session, teacher.id, current)
        if school_class is None:
            raise HTTPException(status_code=403, detail="Нет доступа к классу")
        await session.commit()
        return {"join_key": school_class.join_key, "join_code": school_class.join_code, "join_open": True}
    ok = await set_class_join(session, teacher.id, current, body.action == "enable")
    if not ok:
        raise HTTPException(status_code=403, detail="Нет доступа к классу")
    await session.commit()
    return {"join_open": body.action == "enable"}


TEACHER_KIND = "teacher"


class ChatCreateBody(BaseModel):
    title: str = Field(default="", max_length=200)


class ChatMessageBody(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    class_id: int | None = None


async def _teacher_chat(
    session: AsyncSession, teacher: User, chat_id: int
):
    chat = await chat_store.get_chat(session, teacher.id, TEACHER_KIND, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return chat


def _reply_text(reply: dict) -> str:
    if reply.get("kind") == "draft":
        draft = reply.get("draft") or {}
        return (
            f"Черновик работы: {draft.get('topic') or ''}. "
            f"{draft.get('count') or ''} заданий. Открыл мастер проверки."
        ).strip()
    return str(reply.get("text") or "")[:500] or "Готово."


@router.get("/api/teacher/chats")
async def chats(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    items = await chat_store.list_chats(session, teacher.id, TEACHER_KIND)
    return {
        "items": [
            {
                "id": chat.id,
                "title": chat.title,
                "updated_at": chat.updated_at.isoformat(),
            }
            for chat in items
        ]
    }


@router.post("/api/teacher/chats")
async def create_chat(
    body: ChatCreateBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    chat = await chat_store.create_chat(session, teacher.id, TEACHER_KIND, body.title)
    await session.commit()
    return {"id": chat.id, "title": chat.title}


@router.get("/api/teacher/chats/{chat_id}")
async def chat_messages(
    chat_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    chat = await _teacher_chat(session, teacher, chat_id)
    return chat_store.chat_view(chat, await chat_store.messages_of(session, chat.id))


@router.delete("/api/teacher/chats/{chat_id}")
async def chat_clear(
    chat_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    """Полный сброс истории чата — для тестов и нового диалога."""
    teacher = await user_from_cookie(request, session, "teacher")
    chat = await _teacher_chat(session, teacher, chat_id)
    await chat_store.clear_messages(session, chat.id)
    await session.commit()
    return {"ok": True}


@router.post("/api/teacher/chats/{chat_id}/messages")
async def chat_message(
    chat_id: int,
    body: ChatMessageBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    chat = await _teacher_chat(session, teacher, chat_id)
    settings = request.app.state.settings
    allowed, detail = await chat_store.rate_status(session, teacher.id, settings)
    if not allowed:
        return JSONResponse(
            {"detail": detail, "code": "rate_limited"}, status_code=429
        )
    text = body.text.strip()
    await chat_store.add_message(session, chat, role="user", text=text)
    try:
        report = await _report(request, session, body.class_id)
        history = [
            {"role": getattr(item, "role", ""), "content": getattr(item, "text", "")}
            for item in (await chat_store.messages_of(session, chat.id))[:-1]
        ]
        reply = await _assistant_answer(
            request, session, report, teacher, text, body.class_id, history=history
        )
        await chat_store.add_message(
            session,
            chat,
            role="assistant",
            kind=reply.get("kind") or "text",
            text=_reply_text(reply),
            payload=reply,
        )
        await session.commit()
    except HTTPException:
        raise
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Не получилось сохранить ответ") from None
    return {
        "ok": True,
        "chat_id": chat.id,
        "reply": reply,
        "messages": chat_store.chat_view(
            chat, await chat_store.messages_of(session, chat.id)
        )["messages"],
    }


@router.post("/api/teacher/chats/{chat_id}/messages/photo")
async def chat_message_photo(
    chat_id: int,
    request: Request,
    photo: UploadFile = File(),
    text: str = Form(""),
    class_id: int | None = Form(None),
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    chat = await _teacher_chat(session, teacher, chat_id)
    settings = request.app.state.settings
    allowed, detail = await chat_store.rate_status(session, teacher.id, settings)
    if not allowed:
        return JSONResponse({"detail": detail, "code": "rate_limited"}, status_code=429)
    if len(text) > 1500:
        await photo.close()
        raise HTTPException(status_code=422, detail="Слишком длинный вопрос")
    blob = await photo.read(MAX_PHOTO_BYTES + 1)
    await photo.close()
    if len(blob) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Фото больше 8 МБ")
    if image_kind(blob) is None:
        raise HTTPException(
            status_code=415,
            detail="Нужен файл изображения: JPEG, PNG, WebP или GIF",
        )
    cleaned = text.strip()
    await chat_store.add_message(session, chat, role="user", text=cleaned or "[фото]")
    try:
        tutor = request.app.state.explainer
        combined = cleaned
        if tutor.enabled:
            image = clean_photo(blob)
            seen = await tutor.read_photo(*image) if image is not None else None
            if seen:
                page = normalize(seen)[:1200]
                combined = (
                    f"{cleaned}\n\nТекст со страницы на фото:\n{page}"
                    if cleaned
                    else f"Страница на фото:\n{page}"
                )
        if not combined.strip():
            reply = {
                "kind": "chat",
                "text": "Фото получил, но текст на нём не читается. "
                "Пришлите снимок ровнее или напишите, что на странице.",
            }
        else:
            report = await _report(request, session, class_id)
            history = [
                {"role": getattr(item, "role", ""), "content": getattr(item, "text", "")}
                for item in (await chat_store.messages_of(session, chat.id))[:-1]
            ]
            reply = await _assistant_answer(
                request, session, report, teacher, combined, class_id, history=history
            )
        await chat_store.add_message(
            session,
            chat,
            role="assistant",
            kind=reply.get("kind") or "text",
            text=_reply_text(reply),
            payload=reply,
        )
        await session.commit()
    except HTTPException:
        raise
    except Exception:
        await session.rollback()
        raise HTTPException(status_code=500, detail="Не получилось сохранить ответ") from None
    return {
        "ok": True,
        "chat_id": chat.id,
        "reply": reply,
        "messages": chat_store.chat_view(
            chat, await chat_store.messages_of(session, chat.id)
        )["messages"],
    }
