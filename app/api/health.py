import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.boot import git_sha, schema_heads
from app.db.models import RuntimeFlag
from app.jobs import HEARTBEAT_KEY

router = APIRouter()
logger = logging.getLogger(__name__)


@router.api_route("/health", methods=["GET", "HEAD"])
async def health() -> dict[str, str]:
    return {"status": "ok", "version": git_sha()}


def _warnings(request: Request) -> list[str]:
    notes = getattr(request.app.state, "max_tls", []) or []
    return [note for note in notes if note != "skipped" and not note.endswith("ok")]


def _body(request: Request, status: str, reason: str = "") -> dict[str, object]:
    payload: dict[str, object] = {"status": status, "version": git_sha()}
    warnings = _warnings(request)
    if warnings:
        payload["warnings"] = warnings
    if reason:
        payload["reason"] = reason
    return payload


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    factory = request.app.state.session_factory
    if factory is None:
        logger.error("database unavailable")
        return JSONResponse(_body(request, "unavailable", "database"), status_code=503)
    applied: set[str] | None
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1"))
            try:
                rows = await session.execute(text("SELECT version_num FROM alembic_version"))
                applied = set(rows.scalars().all())
            except Exception:
                await session.rollback()
                applied = None
            beat = await session.scalar(
                select(RuntimeFlag.value).where(RuntimeFlag.key == HEARTBEAT_KEY)
            )
    except Exception:
        logger.error("database unavailable")
        return JSONResponse(_body(request, "unavailable", "database"), status_code=503)
    if applied is None or not schema_heads().issubset(applied):
        logger.error("migrations are behind")
        return JSONResponse(_body(request, "unavailable", "migrations"), status_code=503)
    if not _worker_fresh(beat, request.app.state.settings.worker_stale_seconds):
        logger.error("worker heartbeat is stale")
        return JSONResponse(_body(request, "unavailable", "worker"), status_code=503)
    return JSONResponse(_body(request, "ok"))


def _worker_fresh(value: str | None, stale_seconds: int) -> bool:
    if not value:
        return False
    try:
        beat = int(value)
    except ValueError:
        return False
    return time.time() - beat <= stale_seconds
