import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.bot.service import process_update

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/webhook")
async def webhook(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> JSONResponse:
    settings = request.app.state.settings
    provided = request.headers.get("X-Max-Bot-Api-Secret") or ""
    expected = settings.max_webhook_secret or ""
    if not expected or not hmac.compare_digest(expected, provided):
        return JSONResponse({"detail": "unauthorized"}, status_code=401)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"ok": True})
    if not isinstance(payload, dict):
        return JSONResponse({"ok": True})
    try:
        await process_update(
            session,
            payload,
            request.app.state.sender,
            request.app.state.explainer,
            settings,
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.error("webhook failed: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="error") from None
    return JSONResponse({"ok": True})
