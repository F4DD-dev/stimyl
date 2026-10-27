from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.db.models import User
from app.security.cookies import COOKIE_NAME, MAX_AGE_SECONDS, write_cookie
from app.security.init_data import validate_init_data

router = APIRouter()


class SessionBody(BaseModel):
    init_data: str


@router.post("/api/session")
async def open_session(
    body: SessionBody,
    response: Response,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict[str, str]:
    settings = request.app.state.settings
    if not settings.max_token:
        raise HTTPException(status_code=503, detail="Бот не настроен")
    max_user_id = validate_init_data(body.init_data, settings.max_token)
    if max_user_id is None:
        raise HTTPException(status_code=401, detail="Не удалось проверить вход")
    user = await session.scalar(select(User).where(User.max_user_id == max_user_id))
    if user is None:
        raise HTTPException(status_code=403, detail="Нет доступа")
    response.set_cookie(
        COOKIE_NAME,
        write_cookie(settings.session_secret, user.role, user.max_user_id),
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=MAX_AGE_SECONDS,
    )
    return {"role": user.role}
