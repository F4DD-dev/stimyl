from collections.abc import AsyncIterator

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.domain.accounts import user_for_token
from app.security.cookies import COOKIE_NAME

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

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
    *,
    allow_pending: bool = False,
) -> User:
    """Роль берётся из базы. Аргумент role — какую роль ждёт этот эндпоинт."""
    raw = request.cookies.get(COOKIE_NAME) or _bearer(request)
    if not raw:
        raise HTTPException(status_code=401, detail="Нужен вход")
    found = await user_for_token(session, raw, request.app.state.settings)
    if found is None:
        raise HTTPException(status_code=401, detail="Нужен вход")
    user, row = found
    request.state.csrf = row.csrf_token
    if request.method in UNSAFE:
        _check_origin(request)
        header = request.headers.get("x-csrf-token") or ""
        if not header or not _same(header, row.csrf_token):
            raise HTTPException(status_code=403, detail="Нет доступа")
    if user.status != "active" and not (allow_pending and user.status == "pending"):
        raise HTTPException(status_code=403, detail="Нет доступа")
    if role is not None and user.role != role:
        raise HTTPException(status_code=403, detail="Нет доступа")
    return user


def _bearer(request: Request) -> str:
    """Окно MAX не хранит cookie кабинета. Тот же токен приходит заголовком."""
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def _same(left: str, right: str) -> bool:
    import hmac

    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def _check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    origin = origin.rstrip("/")
    settings = request.app.state.settings
    allowed = set()
    host = request.headers.get("host")
    if host:
        allowed.add(f"http://{host}")
        allowed.add(f"https://{host}")
    if settings.public_base_url:
        allowed.add(settings.public_base_url.rstrip("/"))
    for item in settings.cors_origins.split(","):
        cleaned = item.strip().rstrip("/")
        if cleaned:
            allowed.add(cleaned)
    if origin not in allowed:
        raise HTTPException(status_code=403, detail="Нет доступа")
