import hmac
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.bot.service import process_update
from app.bot.updates import parse_update
from app.domain.account_copy import DB_DOWN

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/webhook")
async def webhook(request: Request) -> JSONResponse:
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
        await _say_db_down(request, payload)
        return JSONResponse({"ok": True})
    try:
        async with factory() as session:
            try:
                await process_update(
                    session,
                    payload,
                    request.app.state.sender,
                    request.app.state.explainer,
                    settings,
                )
                await session.commit()
            except SQLAlchemyError:
                await session.rollback()
                logger.error("webhook database error")
                await _say_db_down(request, payload)
                return JSONResponse({"ok": True})
            except HTTPException:
                await session.rollback()
                raise
            except Exception as exc:
                await session.rollback()
                logger.error("webhook failed: %s", type(exc).__name__)
                raise HTTPException(status_code=500, detail="error") from None
    except SQLAlchemyError:
        logger.error("webhook database error")
        await _say_db_down(request, payload)
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": True})


async def _say_db_down(request: Request, payload: dict) -> None:
    incoming = parse_update(payload)
    if incoming is None:
        return
    try:
        await request.app.state.sender.send_text(
            user_id=incoming.max_user_id,
            chat_id=incoming.chat_id,
            text=DB_DOWN,
            buttons=[],
        )
    except Exception as exc:
        logger.error("db down reply failed: %s", type(exc).__name__)
