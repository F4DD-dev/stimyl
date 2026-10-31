import hmac
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.jobs import enqueue

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/webhook")
async def webhook(request: Request) -> JSONResponse:
    """Сохранить апдейт и сразу ответить. Разбор делает воркер."""
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
    factory = request.app.state.session_factory
    if factory is None:
        logger.error("webhook database error")
        return JSONResponse({"ok": False}, status_code=503)
    try:
        async with factory() as session:
            await enqueue(session, payload)
            await session.commit()
    except SQLAlchemyError:
        logger.error("webhook database error")
        return JSONResponse({"ok": False}, status_code=503)
    return JSONResponse({"ok": True})
