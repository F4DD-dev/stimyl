import asyncio
import logging
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DATABASE_DOWN
from app.api.health import router as health_router
from app.api.pages import router as pages_router
from app.api.session import router as session_router
from app.api.student import router as student_router
from app.api.teacher import router as teacher_router
from app.api.web_login import router as web_login_router
from app.boot import (
    config_error,
    git_sha,
    listen_host,
    listen_port,
    missing_required,
    probe_max_tls,
)
from app.bot.routes import router as webhook_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, request_id
from app.db.session import make_engine, make_session_factory
from app.llm.explainer import build_explainer
from app.max_client.base import NullSender
from app.max_client.client import MaxClient

logger = logging.getLogger(__name__)


class AssetFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


async def _bring_up(app: FastAPI, settings: Settings) -> None:
    """База и TLS после того, как порт уже можно открыть. Ошибка сюда процесс не роняет."""
    notes = ["skipped"]
    if settings.env in {"staging", "prod"}:
        notes = await probe_max_tls()
        for note in notes:
            if note.endswith("ok"):
                logger.info("max tls %s", note)
            else:
                logger.warning("max tls %s", note)
    app.state.max_tls = notes
    engine = make_engine(settings.database_url)
    applied = "-"
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine)
        await _learn_bot_name(app, settings)
        async with app.state.session_factory() as session:
            try:
                rows = await session.execute(text("SELECT version_num FROM alembic_version"))
                applied = ",".join(sorted(rows.scalars().all())) or "-"
            except Exception:
                applied = "-"
        logger.info("database connected")
    except asyncio.CancelledError:
        if app.state.engine is None:
            await engine.dispose()
        raise
    except Exception as exc:
        app.state.boot_error = type(exc).__name__
        logger.error("database unavailable: %s", type(exc).__name__)
        await engine.dispose()
    logger.info(
        "boot version=%s env=%s dev=%s listen=%s:%s migrations=%s db=%s max_tls=%s missing=%s max_token=%s",
        git_sha(),
        settings.env,
        str(settings.dev).lower(),
        listen_host(),
        listen_port(),
        applied,
        "up" if app.state.session_factory is not None else "down",
        ";".join(notes),
        ",".join(missing_required(settings)) or "-",
        "set" if settings.max_token else "missing",
    )


async def _learn_bot_name(app: FastAPI, settings: Settings) -> None:
    """Имя и user_id бота. В open_app contact_id — это user_id, без него payload не доходит."""
    known_name = (settings.bot_username or "").strip()
    short_token = not settings.max_token or len(settings.max_token) <= 20
    if short_token or (known_name and settings.bot_contact_id):
        app.state.bot_username = settings.bot_username
        return
    client = MaxClient(settings.max_token, settings.resolved_ca_path())
    try:
        name, contact_id = await client.my_profile()
    finally:
        await client.aclose()
    if name:
        settings.bot_username = name
    app.state.bot_username = settings.bot_username
    if contact_id:
        settings.bot_contact_id = contact_id
    logger.info("bot username=%s contact_id=%s", settings.bot_username or "-", settings.bot_contact_id or 0)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        reason = config_error(settings)
        if reason:
            logger.error("config: %s", reason)
            raise RuntimeError(reason)
        lowered = settings.database_url.lower()
        if "sslmode=require" in lowered or "ssl=require" in lowered:
            logger.warning("database ssl mode does not verify the server certificate")
        if settings.session_secret == "change-me":
            logger.warning("SESSION_SECRET is the default value")
        app.state.engine = None
        app.state.session_factory = None
        app.state.max_tls = []
        app.state.boot_error = ""
        created_sender = False
        if getattr(app.state, "sender", None) is None:
            if settings.max_token:
                app.state.sender = MaxClient(settings.max_token, settings.resolved_ca_path())
                created_sender = True
            else:
                app.state.sender = NullSender()
        if getattr(app.state, "explainer", None) is None:
            app.state.explainer = build_explainer(settings)
        task = asyncio.create_task(_bring_up(app, settings))
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            if created_sender:
                await app.state.sender.aclose()
            engine = getattr(app.state, "engine", None)
            if engine is not None:
                await engine.dispose()

    app = FastAPI(title="Стимул", lifespan=lifespan)
    app.state.settings = settings

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse({"detail": "Некорректный запрос"}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(_request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        if isinstance(exc, SQLAlchemyError):
            logger.error("database error: %s", type(exc).__name__)
            return JSONResponse({"detail": DATABASE_DOWN}, status_code=503)
        logger.error("unhandled error: %s", type(exc).__name__)
        return JSONResponse({"detail": "error"}, status_code=500)

    app.include_router(health_router)
    app.include_router(webhook_router)
    app.include_router(web_login_router)
    app.include_router(session_router)
    app.include_router(teacher_router)
    app.include_router(student_router)
    app.include_router(pages_router)
    if settings.dev and settings.env != "prod":
        from app.api.dev_whoami import router as dev_router

        app.include_router(dev_router)
    origins = [item.strip() for item in settings.cors_origins.split(",") if item.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )

    @app.middleware("http")
    async def security_and_request_id(request: Request, call_next):
        current = uuid.uuid4().hex
        token = request_id.set(current)
        try:
            response = await call_next(request)
        finally:
            request_id.reset(token)
        response.headers["X-Request-ID"] = current
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://st.max.ru; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' blob: data:; "
            "connect-src 'self'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        return response

    web = Path(__file__).resolve().parent / "web"
    app.mount("/assets", AssetFiles(directory=web), name="assets")
    return app
