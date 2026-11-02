import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, db_session, user_from_cookie
from app.domain.account_copy import BLOCKED, OPEN_FROM_CHAT, PENDING_BROWSER
from app.domain.accounts import (
    BOT_PROVIDER,
    WEBAPP_PROVIDER,
    claim_webapp_ticket,
    ensure_webapp_identity,
    open_browser_session,
    user_by_provider,
    write_audit,
)
from app.security.cookies import COOKIE_NAME, cookie_params
from app.security.init_data import read_init_data

router = APIRouter()
logger = logging.getLogger(__name__)


class SessionBody(BaseModel):
    init_data: str
    start_param: str = ""


def launch_param(signed: str, hinted: str) -> str:
    """Билет из подписи важнее. Отдельное поле принимаем только как тот же формат payload."""
    if signed:
        return signed
    hinted = (hinted or "").strip()
    if re.fullmatch(r"[\w-]{1,512}", hinted):
        return hinted
    return ""


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
    fields = read_init_data(body.init_data, settings.max_token)
    if fields is None:
        logger.info("miniapp session rejected reason=unsigned")
        raise HTTPException(status_code=401, detail="Не удалось проверить вход")
    external_id = fields["user_id"]
    signed_param = fields.get("start_param") or ""
    start_param = launch_param(signed_param, body.start_param)
    logger.info(
        "miniapp start_param=%s",
        "signed" if signed_param else "hint" if start_param else "absent",
    )
    user = await user_by_provider(session, WEBAPP_PROVIDER, external_id)
    if user is None and settings.allow_id_match:
        matched = await user_by_provider(session, BOT_PROVIDER, external_id)
        if matched is not None and matched.status == "active" and matched.deleted_at is None:
            if await ensure_webapp_identity(session, matched, external_id):
                user = matched
    if user is None and start_param:
        user = await claim_webapp_ticket(session, start_param, external_id, settings)
    if user is None:
        logger.info("miniapp session rejected reason=unlinked")
        await session.commit()
        raise HTTPException(status_code=409, detail=OPEN_FROM_CHAT)
    if user.status == "blocked":
        logger.info("miniapp session rejected reason=blocked")
        raise HTTPException(status_code=403, detail=BLOCKED)
    if user.status != "active":
        logger.info("miniapp session rejected reason=pending")
        raise HTTPException(status_code=403, detail=PENDING_BROWSER)
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
    return {"role": user.role, "csrf": csrf, "token": raw}


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
