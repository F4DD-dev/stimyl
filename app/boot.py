"""Старт без секретов в логе. Порт от этого модуля не зависит."""

import asyncio
import logging
import os
import ssl
import subprocess
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)

MAX_HOSTS = ("platform-api.max.ru", "platform-api2.max.ru")
_SHA_KEYS = ("GIT_SHA", "COMMIT_SHA", "SOURCE_COMMIT")


def listen_host() -> str:
    return os.environ.get("HOST", "0.0.0.0").strip() or "0.0.0.0"


def listen_port() -> int:
    raw = os.environ.get("PORT", "8000").strip() or "8000"
    try:
        port = int(raw)
    except ValueError:
        raise SystemExit(f"PORT is not a number: {raw}") from None
    if not 1 <= port <= 65535:
        raise SystemExit(f"PORT is out of range: {port}")
    return port


def git_sha() -> str:
    for key in _SHA_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return value[:40]
    root = Path(__file__).resolve().parents[1]
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            timeout=2,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = out.decode().strip()
    return sha[:40] or "unknown"


def missing_required(settings: Settings) -> list[str]:
    missing: list[str] = []
    if not settings.database_url:
        missing.append("DATABASE_URL")
    return missing


def config_error(settings: Settings) -> str | None:
    missing = missing_required(settings)
    if missing:
        return "не заданы переменные: " + ", ".join(missing)
    if settings.dev and settings.env == "prod":
        return "DEV=true запрещён при ENV=prod"
    try:
        listen_port()
    except SystemExit as exc:
        return str(exc)
    return None


def schema_heads() -> set[str]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config("alembic.ini"))
    return set(script.get_heads())


def preflight(settings: Settings | None = None) -> None:
    configure_logging()
    settings = settings or get_settings()
    reason = config_error(settings)
    try:
        port_text = str(listen_port())
    except SystemExit:
        port_text = "-"
    logger.info(
        "start version=%s env=%s dev=%s listen=%s:%s missing=%s",
        git_sha(),
        settings.env,
        str(settings.dev).lower(),
        listen_host(),
        port_text,
        ",".join(missing_required(settings)) or "-",
    )
    if reason:
        logger.error("config: %s", reason)
        raise SystemExit(1)


async def probe_max_tls(
    hosts: tuple[str, ...] = MAX_HOSTS,
    timeout: float = 5,
) -> list[str]:
    """Проверить TLS к MAX. Ошибка — строка предупреждения, не исключение."""
    context = ssl.create_default_context()
    notes: list[str] = []
    for host in hosts:
        try:
            reader_writer = await asyncio.wait_for(
                asyncio.open_connection(host, 443, ssl=context),
                timeout=timeout,
            )
            _reader, writer = reader_writer
            writer.close()
            await writer.wait_closed()
            notes.append(f"{host}: ok")
        except Exception as exc:
            notes.append(f"{host}: {type(exc).__name__}")
    return notes


LLM_EDGE_HOSTS = (
    "openrouter.ai",
    "api.giga.chat",
    "ngw.devices.sberbank.ru",
    "integrate.api.nvidia.com",
    "llm.api.cloud.yandex.net",
    "api.siliconflow.cn",
    "api.deepseek.com",
    "text.pollinations.ai",
)


async def probe_llm_edges(hosts: tuple[str, ...] = LLM_EDGE_HOSTS, timeout: float = 8) -> list[str]:
    """GET на корень кандидатов браузерным отпечатком. 403+Access denied — Cloudflare
    режет IP до API, как openrouter с Timeweb. Любой другой статус — до API дошли."""
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        return ["no curl_cffi"]
    async def check(session, host: str) -> str:
        try:
            response = await session.get(f"https://{host}/", verify=False)
            return f"{host}: {response.status_code}"
        except Exception as exc:
            return f"{host}: {type(exc).__name__}"

    async with AsyncSession(impersonate="chrome", timeout=timeout) as session:
        return list(await asyncio.gather(*(check(session, host) for host in hosts)))


def main() -> None:
    preflight()


if __name__ == "__main__":
    main()
