from collections.abc import AsyncIterator

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.domain.accounts import user_for_token
from app.security.cookies import COOKIE_NAME

DATABASE_DOWN = "База сейчас недоступна. Попробуйте ещё раз."


async def db_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    if factory is None:
        raise HTTPException(status_code=503, detail=DATABASE_DOWN)
    async with factory() as session:
        yield session


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client is None:
        return ""
    return request.client.host[:64]


async def user_from_cookie(
    request: Request,
    session: AsyncSession,
    role: str | None = None,
) -> User:
    """Роль берётся из базы. Аргумент role — какую роль ждёт этот эндпоинт."""
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        raise HTTPException(status_code=401, detail="Нужен вход")
    found = await user_for_token(session, raw, request.app.state.settings)
    if found is None:
        raise HTTPException(status_code=401, detail="Нужен вход")
    user, _row = found
    if user.status != "active":
        raise HTTPException(status_code=403, detail="Нет доступа")
    if role is not None and user.role != role:
        raise HTTPException(status_code=403, detail="Нет доступа")
    return user
