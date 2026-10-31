from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, db_session, user_from_cookie
from app.domain.account_copy import LINK_REQUIRED
from app.domain.accounts import WEBAPP_PROVIDER, open_browser_session, user_by_provider, write_audit
from app.security.cookies import COOKIE_NAME, cookie_params
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
    external_id = validate_init_data(body.init_data, settings.max_token)
    if external_id is None:
        raise HTTPException(status_code=401, detail="Не удалось проверить вход")
    # Поле user.id из initData не ищем среди user_id бота. См. docs/ACCOUNTS.md.
    user = await user_by_provider(session, WEBAPP_PROVIDER, external_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=403, detail=LINK_REQUIRED)
    raw, csrf = await open_browser_session(
        session,
        user,
        request.headers.get("user-agent", ""),
        client_ip(request),
        settings,
    )
    await write_audit(session, user.id, "login_webapp", user.id, client_ip(request), None)
    await session.commit()
    response.set_cookie(COOKIE_NAME, raw, **cookie_params(settings.cookie_secure))
    return {"role": user.role, "csrf": csrf}


@router.get("/api/session")
async def current_session(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict[str, str]:
    user = await user_from_cookie(request, session)
    return {
        "role": user.role,
        "display_name": user.display_name,
        "csrf": getattr(request.state, "csrf", ""),
    }
