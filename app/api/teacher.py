from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, user_from_cookie
from app.bot.assist import clean_photo
from app.bot.compose import ASSISTANT_OFF, NO_BANK, class_summary, compose_draft
from app.bot.service import class_report
from app.db.models import ClassTeacher, Enrollment, SchoolClass, User
from app.domain.accounts import approve_enrollment, rotate_class_key, set_class_join
from app.domain.assist import match_students
from app.domain.images import image_kind
from app.domain.library import delete_material, list_materials, save_material
from app.domain.materials import extract_text, file_kind, normalize
from app.domain.onboarding import claims_for, reviewer_name
from app.domain.schoolwork import classes_of, list_teacher_works, owned_class

router = APIRouter()

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
    composed = await compose_draft(
        session,
        request.app.state.explainer,
        class_id=await owned_class(session, teacher, body.class_id),
        topic=body.topic,
        goal=body.goal,
        count=body.count,
        difficulty=body.difficulty,
        audience=body.audience,
        students=_students(report, body),
        use_material=body.use_material,
    )
    if composed.error or composed.draft is None:
        raise HTTPException(status_code=composed.status, detail=composed.error or NO_BANK)
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


@router.post("/api/teacher/assistant")
async def assistant(
    body: AskBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    """Просьба учителя словами. Работу не отправляет: возвращает черновик на проверку."""
    report = await _report(request, session, body.class_id)
    tutor = request.app.state.explainer
    if not tutor.enabled:
        raise HTTPException(status_code=503, detail=ASSISTANT_OFF)
    titles = [topic.title for topic in report.topics]
    ask = await tutor.read_teacher(body.text, titles)
    if ask is None:
        raise HTTPException(status_code=503, detail=ASSISTANT_OFF)
    if ask.intent == "summary":
        return {"kind": "summary", "text": class_summary(report)}
    if ask.intent != "work" or not ask.topic:
        return {
            "kind": "help",
            "text": "Напишите тему и что проверить, например: «Дроби, сложение с разными знаменателями, 4 задания».",
        }
    roster = [(student.user_id, student.display_name) for student in report.students]
    ids, names, unknown = match_students(list(ask.students), roster)
    audience = "selected" if ids else "class"
    teacher = await user_from_cookie(request, session, "teacher")
    composed = await compose_draft(
        session,
        tutor,
        class_id=await owned_class(session, teacher, body.class_id),
        topic=ask.topic,
        goal=ask.goal or ask.topic,
        count=ask.count,
        difficulty=ask.difficulty,
        audience=audience,
        students=names if ids else [name for _id, name in roster],
        use_material=ask.use_material,
    )
    if composed.error or composed.draft is None:
        raise HTTPException(status_code=composed.status, detail=composed.error or NO_BANK)
    return {
        "kind": "draft",
        "draft": composed.draft,
        "wizard": {
            "topic": ask.topic,
            "goal": ask.goal or ask.topic,
            "count": composed.draft["count"],
            "difficulty": ask.difficulty,
            "audience": audience,
            "student_ids": ids,
            "students": names,
            "use_material": ask.use_material,
        },
        "unknown_students": unknown,
    }


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
