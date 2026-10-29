from collections.abc import AsyncIterator

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.security.cookies import COOKIE_NAME, read_cookie

DATABASE_DOWN = "База сейчас недоступна. Попробуйте ещё раз."


async def db_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    if factory is None:
        raise HTTPException(status_code=503, detail=DATABASE_DOWN)
    async with factory() as session:
        yield session


async def user_from_cookie(request: Request, session: AsyncSession, role: str) -> User:
    settings = request.app.state.settings
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        raise HTTPException(status_code=401, detail="Нужен вход из MAX")
    parsed = read_cookie(settings.session_secret, raw)
    if parsed is None:
        raise HTTPException(status_code=401, detail="Нужен вход из MAX")
    cookie_role, max_user_id = parsed
    if cookie_role != role:
        raise HTTPException(status_code=403, detail="Нет доступа")
    user = await session.scalar(select(User).where(User.max_user_id == max_user_id))
    if user is None or user.role != role:
        raise HTTPException(status_code=403, detail="Нет доступа")
    return user
