import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import DATABASE_DOWN
from app.api.health import router as health_router
from app.api.pages import router as pages_router
from app.api.session import router as session_router
from app.api.student import router as student_router
from app.api.teacher import router as teacher_router
from app.bot.routes import router as webhook_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.database_url) if settings.database_url else None
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine) if engine is not None else None
        created_sender = False
        if getattr(app.state, "sender", None) is None:
            if settings.max_token:
                app.state.sender = MaxClient(settings.max_token, settings.resolved_ca_path())
                created_sender = True
            else:
                app.state.sender = NullSender()
        if getattr(app.state, "explainer", None) is None:
            app.state.explainer = build_explainer(settings)
        yield
        if created_sender:
            await app.state.sender.aclose()
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
    app.include_router(session_router)
    app.include_router(teacher_router)
    app.include_router(student_router)
    app.include_router(pages_router)
    web = Path(__file__).resolve().parent / "web"
    app.mount("/assets", AssetFiles(directory=web), name="assets")
    return app
