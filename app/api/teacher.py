from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, user_from_cookie
from app.bot.service import class_report
from app.db.models import ClassTeacher, Enrollment, SchoolClass, User
from app.domain.accounts import approve_enrollment, rotate_class_key, set_class_join
from app.domain.drafts import build_check_draft, build_stimul_draft
from app.domain.onboarding import claims_for, reviewer_name
from app.domain.schoolwork import classes_of, list_teacher_works

router = APIRouter()

MATERIAL_MISSING = (
    "Нет сохранённых фрагментов урока. "
    "Не собираю задания по параграфу и не выдумываю источник."
)
DELIVERY_MISSING = (
    "Отправка работ в MAX ещё не подключена. Черновик не сохранён и ученикам не ушёл."
)
NO_BANK = "По этой теме задания сам не соберу. Напишите вопросы и верные ответы."


class DraftBody(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=300)
    count: int = Field(ge=1, le=6)
    difficulty: Literal["easy", "normal", "hard"]
    audience: Literal["class", "selected"]
    students: list[str] = Field(default_factory=list, max_length=40)
    use_material: bool = False


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


def _prepare(report, body: DraftBody, quiz_enabled: bool) -> dict:
    if not quiz_enabled:
        raise HTTPException(status_code=404, detail="Сборка проверок выключена")
    if body.use_material:
        raise HTTPException(status_code=409, detail=MATERIAL_MISSING)
    students = _students(report, body)
    draft = build_check_draft(
        body.topic,
        body.goal,
        body.count,
        body.difficulty,
        body.audience,
        students,
    )
    if draft is None:
        draft = build_stimul_draft(
            body.topic,
            body.goal,
            body.count,
            body.difficulty,
            body.audience,
            students,
        )
    if draft is None:
        raise HTTPException(status_code=409, detail=NO_BANK)
    return draft


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
    payload["pending_claims"] = await claims_for(session, teacher) if teacher.can_manage_school else []
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
    report = await _report(request, session)
    return _prepare(report, body, request.app.state.settings.feature_quiz)


@router.post("/api/teacher/assignments", status_code=501)
async def create_assignment(
    body: DraftBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> None:
    report = await _report(request, session)
    _prepare(report, body, request.app.state.settings.feature_quiz)
    raise HTTPException(status_code=501, detail=DELIVERY_MISSING)


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
