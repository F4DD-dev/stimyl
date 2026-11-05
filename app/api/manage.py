"""Управление тестовым классом. Доступ только у учителя с can_manage_school."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, user_from_cookie
from app.db.models import User
from app.domain.onboarding import accept_claim, claims_for, reject_claim
from app.domain.roster import appoint, catalog, list_people, person_detail, update_person, withdraw

router = APIRouter()


class PersonBody(BaseModel):
    role: str | None = None
    status: str | None = None
    can_manage_school: bool | None = None
    display_name: str | None = Field(default=None, max_length=200)


class AppointmentBody(BaseModel):
    user_id: int
    class_id: int
    subject_id: int


async def _teacher(request: Request, session: AsyncSession) -> User:
    return await user_from_cookie(request, session, "teacher")


async def _manager(request: Request, session: AsyncSession) -> User:
    user = await user_from_cookie(request, session, "teacher")
    if not user.can_manage_school:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return user


@router.get("/api/manage/claims")
async def claims(request: Request, session: AsyncSession = Depends(db_session)) -> dict:
    actor = await _teacher(request, session)
    return {"items": await claims_for(session, actor)}


@router.post("/api/manage/claims/{user_id}/accept")
async def accept(
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    actor = await _teacher(request, session)
    ok, detail = await accept_claim(session, actor, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail=detail)
    await session.commit()
    return {"ok": True, "display_name": detail}


@router.post("/api/manage/claims/{user_id}/reject")
async def reject(
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    actor = await _teacher(request, session)
    ok, detail = await reject_claim(session, actor, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail=detail)
    await session.commit()
    return {"ok": True, "display_name": detail}


@router.get("/api/manage/people")
async def people(
    request: Request,
    q: str = "",
    role: str = "",
    status: str = "",
    session: AsyncSession = Depends(db_session),
) -> dict:
    await _manager(request, session)
    return {"items": await list_people(session, query=q, role=role, status=status)}


@router.get("/api/manage/people/{user_id}")
async def person(
    user_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    await _manager(request, session)
    found = await person_detail(session, user_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Человека нет")
    return found


@router.post("/api/manage/people/{user_id}")
async def change_person(
    user_id: int,
    body: PersonBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    actor = await _manager(request, session)
    payload, error, status = await update_person(
        session,
        actor,
        user_id,
        role=body.role,
        status=body.status,
        can_manage_school=body.can_manage_school,
        display_name=body.display_name,
    )
    if error:
        raise HTTPException(status_code=status, detail=error)
    await session.commit()
    return payload


@router.get("/api/manage/catalog")
async def school_catalog(request: Request, session: AsyncSession = Depends(db_session)) -> dict:
    await _manager(request, session)
    return await catalog(session)


@router.post("/api/manage/appointments")
async def add_appointment(
    body: AppointmentBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    await _manager(request, session)
    ok, detail = await appoint(
        session,
        user_id=body.user_id,
        class_id=body.class_id,
        subject_id=body.subject_id,
    )
    if not ok:
        raise HTTPException(status_code=422, detail=detail)
    await session.commit()
    return {"ok": True, "display_name": detail}


@router.post("/api/manage/appointments/remove")
async def remove_appointment(
    body: AppointmentBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    await _manager(request, session)
    ok = await withdraw(
        session,
        user_id=body.user_id,
        class_id=body.class_id,
        subject_id=body.subject_id,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Назначения нет")
    await session.commit()
    return {"ok": True}
