"""Работы учителя и ответы ученика. Сохранение подтверждается только после записи в базу."""

from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, user_from_cookie
from app.core.config import get_settings
from app.db.models import Notice, User
from app.domain.schoolwork import (
    attach_resource,
    detach_resource,
    list_student_works,
    publish_work,
    save_work,
    student_assignment_note,
    student_resource_file,
    submit_work,
    work_results,
)

router = APIRouter()


class OwnItem(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    reference: str = Field(min_length=1, max_length=64)


class WorkBody(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=300)
    count: int = Field(ge=1, le=6)
    difficulty: str = Field(pattern="^(easy|normal|hard)$")
    audience: str = Field(pattern="^(class|selected)$")
    students: list[str] = Field(default_factory=list, max_length=40)
    student_ids: list[int] = Field(default_factory=list, max_length=40)
    prompts: list[str] | None = Field(default=None, max_length=6)
    items: list[OwnItem] | None = Field(default=None, max_length=6)
    blurb: str = Field(default="", max_length=800)
    due_at: str | None = Field(default=None, max_length=40)
    class_id: int | None = None
    work_id: int | None = None
    subject_id: int | None = None


class AnswerItem(BaseModel):
    item_id: int
    answer: str = Field(min_length=1, max_length=200)


class AnswerBody(BaseModel):
    answers: list[AnswerItem] = Field(min_length=1, max_length=6)


def _due(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Некорректный срок") from exc
    return parsed


async def _finish(session: AsyncSession, payload, error, status) -> dict:
    if error:
        raise HTTPException(status_code=status, detail=error)
    await session.commit()
    return payload


@router.post("/api/teacher/works")
async def create_work(
    body: WorkBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    payload, error, status = await save_work(
        session,
        teacher,
        class_id=body.class_id,
        topic=body.topic,
        goal=body.goal,
        count=body.count,
        difficulty=body.difficulty,
        audience=body.audience,
        students=body.students,
        student_ids=body.student_ids,
        prompts=body.prompts,
        due_at=_due(body.due_at),
        work_id=body.work_id,
        own_items=None
        if body.items is None
        else [(item.prompt, item.reference) for item in body.items],
        blurb=body.blurb,
        subject_id=body.subject_id,
    )
    return await _finish(session, payload, error, status)


@router.post("/api/teacher/works/{work_id}/publish")
async def publish(
    work_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    payload, error, status = await publish_work(session, teacher, work_id)
    return await _finish(session, payload, error, status)


@router.get("/api/teacher/works/{work_id}")
async def teacher_work(
    work_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    payload, error, status = await work_results(session, teacher, work_id)
    if error:
        raise HTTPException(status_code=status, detail=error)
    if session.info.get("work_repaired"):
        await session.commit()
    return payload


@router.get("/api/student/works")
async def student_works(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    student = await user_from_cookie(request, session, "student")
    return {
        "items": await list_student_works(session, student),
        "reason": await student_assignment_note(session, student),
    }


@router.post("/api/student/works/{work_id}/answers")
async def student_answers(
    work_id: int,
    body: AnswerBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    student = await user_from_cookie(request, session, "student")
    payload, error, status = await submit_work(
        session,
        student,
        work_id,
        [(item.item_id, item.answer) for item in body.answers],
        request.app.state.settings,
    )
    return await _finish(session, payload, error, status)


@router.post("/api/teacher/works/{work_id}/resources")
async def add_resource(
    work_id: int,
    request: Request,
    title: str = Form(""),
    url: str = Form(""),
    file: UploadFile | None = File(None),
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    blob = None
    file_name = ""
    mime = ""
    if file is not None:
        limit = get_settings().material_max_mb * 1024 * 1024
        blob = await file.read(limit + 1)
        await file.close()
        if len(blob) > limit:
            raise HTTPException(status_code=413, detail=f"Файл больше {get_settings().material_max_mb} МБ")
        file_name = file.filename or "material"
        mime = file.content_type or "application/octet-stream"
    payload, error, status = await attach_resource(
        session,
        teacher,
        work_id,
        title=title,
        url=url or None,
        file_name=file_name,
        mime=mime,
        blob=blob,
    )
    return await _finish(session, payload, error, status)


@router.delete("/api/teacher/works/{work_id}/resources/{resource_id}")
async def remove_resource(
    work_id: int,
    resource_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    ok, error, status = await detach_resource(session, teacher, work_id, resource_id)
    if error:
        raise HTTPException(status_code=status, detail=error)
    await session.commit()
    return {"ok": ok}


@router.get("/api/student/works/{work_id}/resources/{resource_id}/file")
async def resource_file(
    work_id: int,
    resource_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> Response:
    student = await user_from_cookie(request, session, "student")
    row, error, status = await student_resource_file(session, student, work_id, resource_id)
    if error or row is None or row.blob is None:
        raise HTTPException(status_code=status or 404, detail=error or "Материала нет")
    safe = "".join(ch for ch in row.title if ch.isalnum() or ch in " ._-")[:120].strip() or "material"
    return Response(
        content=bytes(row.blob),
        media_type=row.mime or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename=\"{safe}\"; filename*=UTF-8''{quote(row.title[:180])}"},
    )


@router.get("/api/notices")
async def notices(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    user = await user_from_cookie(request, session)
    rows = list(
        await session.scalars(
            select(Notice).where(Notice.user_id == user.id).order_by(Notice.id.desc()).limit(40)
        )
    )
    unread = sum(1 for row in rows if row.read_at is None)
    return {
        "unread": unread,
        "items": [
            {
                "id": row.id,
                "kind": row.kind,
                "title": row.title,
                "body": row.body,
                "ref_id": row.ref_id,
                "read": row.read_at is not None,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }


@router.post("/api/notices/{notice_id}/read")
async def read_notice(
    notice_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    user: User = await user_from_cookie(request, session)
    row = await session.get(Notice, notice_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Уведомления нет")
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        await session.commit()
    return {"ok": True}
