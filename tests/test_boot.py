import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.boot import listen_host, listen_port, preflight, schema_heads
from app.core.config import Settings, get_settings
from app.db.migrate import upgrade_head
from app.db.models import RuntimeFlag
from app.jobs import HEARTBEAT_KEY
from app.main import _learn_bot_name


def test_listen_defaults_to_every_interface(monkeypatch):
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    assert listen_host() == "0.0.0.0"
    assert listen_port() == 8000


def test_preflight_rejects_a_missing_database():
    settings = Settings(database_url="", env="dev", dev=False, session_secret="session-secret")
    with pytest.raises(SystemExit):
        preflight(settings)


def test_preflight_rejects_dev_on_prod():
    settings = Settings(
        database_url="postgresql+asyncpg://stimul:stimul@127.0.0.1:5432/stimul",
        env="prod",
        dev=True,
        session_secret="session-secret",
    )
    with pytest.raises(SystemExit):
        preflight(settings)


async def test_web_process_learns_the_bot_contact(monkeypatch):
    class Fake:
        def __init__(self, token: str, ca: str | None) -> None:
            assert len(token) > 20
            assert ca is None or isinstance(ca, str)

        async def my_profile(self) -> tuple[str, int]:
            return "se14271630_1_bot", 515445879

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("app.main.MaxClient", Fake)
    app = SimpleNamespace(state=SimpleNamespace())
    settings = Settings(
        database_url="postgresql+asyncpg://stimul:stimul@127.0.0.1:5432/stimul",
        max_token="x" * 21,
        session_secret="session-secret",
        env="dev",
        bot_username="already",
    )
    await _learn_bot_name(app, settings)
    assert settings.bot_username == "se14271630_1_bot"
    assert settings.bot_contact_id == 515445879
    assert app.state.bot_username == "se14271630_1_bot"


def test_shipped_root_is_one_certificate_and_the_image_does_not_rehash_a_bundle():
    pem = Path("certs/russian_trusted_root_ca.pem").read_text(encoding="utf-8")
    assert pem.count("BEGIN CERTIFICATE") == 1
    docker = Path("Dockerfile").read_text(encoding="utf-8")
    entry = Path("docker/entrypoint.sh").read_text(encoding="utf-8")
    assert "update-ca-certificates" not in docker
    assert "ca_bundle" not in docker.lower()
    assert "ca_bundle" not in entry.lower()
    assert "uvicorn main:app --host" in entry
    assert "alembic upgrade" not in entry


async def test_ready_names_migrations_and_a_stopped_worker(api):
    factory = api.app.state.session_factory
    async with factory() as session:
        row = await session.get(RuntimeFlag, HEARTBEAT_KEY)
        assert row is not None
        row.value = "1"
        await session.commit()
    stopped = await api.client.get("/ready")
    assert stopped.status_code == 503
    assert stopped.json()["reason"] == "worker"

    heads = sorted(schema_heads())
    async with factory() as session:
        row = await session.get(RuntimeFlag, HEARTBEAT_KEY)
        row.value = "9999999999"
        await session.execute(text("DELETE FROM alembic_version"))
        await session.commit()
    try:
        behind = await api.client.get("/ready")
        assert behind.status_code == 503
        assert behind.json()["reason"] == "migrations"
    finally:
        async with factory() as session:
            await session.execute(text("DELETE FROM alembic_version"))
            for head in heads:
                await session.execute(
                    text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                    {"v": head},
                )
            await session.commit()


async def test_tls_warning_does_not_take_ready_down(api):
    api.app.state.max_tls = ["platform-api2.max.ru: SSLError", "platform-api.max.ru: ok"]
    response = await api.client.get("/ready")
    assert response.status_code == 200
    assert response.json()["warnings"] == ["platform-api2.max.ru: SSLError"]


async def test_two_migrations_take_the_advisory_lock(database_url):
    get_settings.cache_clear()
    first, second = await asyncio.gather(
        asyncio.to_thread(upgrade_head),
        asyncio.to_thread(upgrade_head),
    )
    assert first
    assert first == second
    assert database_url
