import os
import ssl
from collections.abc import Mapping

from sqlalchemy import event
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}


def prepare_database_url(url: str) -> tuple[str, dict[str, object]]:
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgres://")
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    if not url.startswith("postgresql"):
        return url, {}
    parsed = make_url(url)
    query = dict(parsed.query)
    mode = (
        _query_text(query.pop("sslmode", "")).lower() or _query_text(query.pop("ssl", "")).lower()
    )
    query.pop("ssl", None)
    remote = (parsed.host or "") not in _LOCAL_HOSTS
    if remote and mode in {"", "require", "prefer"}:
        mode = "verify-full"
    connect_args: dict[str, object] = {"timeout": 10}
    if mode and mode != "disable":
        ca_path = os.environ.get("DATABASE_SSL_CA") or ""
        context = ssl.create_default_context(cafile=ca_path) if ca_path else ssl.create_default_context()
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = mode == "verify-full"
        connect_args["ssl"] = context
    cleaned = parsed.set(query=query).render_as_string(hide_password=False)
    return cleaned, connect_args


def _query_text(value: object) -> str:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value or "")


def make_engine(url: str, *, null_pool: bool = False) -> AsyncEngine:
    cleaned, connect_args = prepare_database_url(url)
    pool_kwargs: Mapping[str, object] = {"poolclass": NullPool} if null_pool else {}
    engine = create_async_engine(
        cleaned,
        pool_pre_ping=True,
        connect_args=connect_args,
        **pool_kwargs,
    )
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
