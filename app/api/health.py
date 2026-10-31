import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.db.models import RuntimeFlag
from app.jobs import HEARTBEAT_KEY

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
            beat = await session.scalar(
                select(RuntimeFlag.value).where(RuntimeFlag.key == HEARTBEAT_KEY)
            )
    except Exception:
        logger.error("database unavailable")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    if not _worker_fresh(beat, request.app.state.settings.worker_stale_seconds):
        logger.error("worker heartbeat is stale")
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})


def _worker_fresh(value: str | None, stale_seconds: int) -> bool:
    if not value:
        return False
    try:
        beat = int(value)
    except ValueError:
        return False
    return time.time() - beat <= stale_seconds
