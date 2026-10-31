"""Вход учителя в браузер по коду из бота. Ученикам этот путь закрыт."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, db_session, user_from_cookie
from app.domain.accounts import (
    list_sessions,
    redeem_ticket,
    redeem_web_code,
    revoke_all,
    revoke_session,
)
from app.security.cookies import COOKIE_NAME, cookie_params

router = APIRouter()


class CodeBody(BaseModel):
    public_id: str = Field(min_length=4, max_length=16)
    code: str = Field(min_length=4, max_length=8)


class TicketBody(BaseModel):
    ticket: str = Field(min_length=20, max_length=128)


def _accept(result, response: Response, secure: bool) -> dict[str, str]:
    response.set_cookie(COOKIE_NAME, result.token, **cookie_params(secure))
    return {"role": result.user.role, "csrf": result.csrf}


@router.post("/api/web-login")
async def web_login(
    body: CodeBody,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(db_session),
) -> dict[str, str]:
    settings = request.app.state.settings
    result = await redeem_web_code(
        session,
        body.public_id,
        body.code,
        settings,
        client_ip(request),
        request.headers.get("user-agent", ""),
    )
    if not result.ok or result.user is None:
        await session.commit()
        raise HTTPException(status_code=result.status, detail=result.detail)
    await session.commit()
    return _accept(result, response, settings.cookie_secure)


@router.post("/api/web-login/ticket")
async def web_ticket(
    body: TicketBody,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(db_session),
) -> dict[str, str]:
    settings = request.app.state.settings
    result = await redeem_ticket(
        session,
        body.ticket,
        settings,
        client_ip(request),
        request.headers.get("user-agent", ""),
    )
    if not result.ok or result.user is None:
        await session.commit()
        raise HTTPException(status_code=result.status, detail=result.detail)
    await session.commit()
    return _accept(result, response, settings.cookie_secure)


@router.post("/api/logout")
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(db_session),
) -> dict[str, str]:
    pair = await _pair(request, session)
    if pair is not None:
        await revoke_session(session, pair[1])
        await session.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": "true"}


@router.post("/api/logout-all")
async def logout_all(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(db_session),
) -> dict[str, str]:
    user = await user_from_cookie(request, session)
    await revoke_all(session, user.id)
    await session.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": "true"}


@router.get("/api/sessions")
async def sessions(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    user = await user_from_cookie(request, session)
    current = await _pair(request, session)
    current_id = current[1].id if current else None
    rows = await list_sessions(session, user.id)
    return {
        "sessions": [
            {
                "id": row.id,
                "created_at": row.created_at.isoformat(),
                "ip": row.ip,
                "user_agent": row.user_agent,
                "current": row.id == current_id,
            }
            for row in rows
        ]
    }


@router.delete("/api/sessions/{session_id}")
async def revoke_one(
    session_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict[str, str]:
    user = await user_from_cookie(request, session)
    rows = await list_sessions(session, user.id)
    found = next((row for row in rows if row.id == session_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    await revoke_session(session, found)
    await session.commit()
    return {"ok": "true"}


async def _pair(request: Request, session: AsyncSession) -> tuple | None:
    from app.domain.accounts import user_for_token

    raw = request.cookies.get(COOKIE_NAME) or ""
    return await user_for_token(session, raw, request.app.state.settings)
