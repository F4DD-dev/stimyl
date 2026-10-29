import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter()
logger = logging.getLogger(__name__)


@router.api_route("/health", methods=["GET", "HEAD"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    factory = request.app.state.session_factory
    if factory is None:
        logger.error("database unavailable")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        logger.error("database unavailable")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})
