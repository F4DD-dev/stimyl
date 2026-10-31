import pytest

from app.core.config import Settings
from app.main import create_app


async def test_head_on_the_front_page_is_allowed(api):
    response = await api.client.head("/")
    assert response.status_code == 200


async def test_cabinet_is_the_teacher_app(api):
    response = await api.client.get("/cabinet")
    assert response.status_code == 200
    assert 'data-entry="teacher"' in response.text
    assert "/assets/js/app.js" in response.text
    assert "Стимул на связи" not in response.text
    head = await api.client.head("/cabinet")
    assert head.status_code == 200


async def test_health_and_ready(api):
    health = await api.client.get("/health")
    ready = await api.client.get("/ready")
    missing = await api.client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["version"]
    assert ready.status_code == 200
    assert ready.json()["status"] == "ok"
    assert missing.status_code == 404


def _paths(application) -> set[str]:
    found: set[str] = set()
    for route in application.routes:
        path = getattr(route, "path", "")
        if path:
            found.add(path)
        router = getattr(route, "original_router", None)
        for item in getattr(router, "routes", []) or []:
            item_path = getattr(item, "path", "")
            if item_path:
                found.add(item_path)
    return found


async def test_dev_true_and_prod_does_not_start(database_url):
    settings = Settings(
        database_url=database_url,
        session_secret="session-secret",
        dev=True,
        env="prod",
    )
    application = create_app(settings)
    assert "/dev/whoami" not in _paths(application)
    with pytest.raises(RuntimeError, match="DEV=true"):
        async with application.router.lifespan_context(application):
            pass


async def test_staging_dev_exposes_whoami_page(database_url):
    settings = Settings(
        database_url=database_url,
        session_secret="session-secret",
        dev=True,
        env="staging",
    )
    application = create_app(settings)
    assert "/dev/whoami" in _paths(application)


async def test_service_does_not_start_without_a_database():
    settings = Settings(database_url="", session_secret="session-secret")
    application = create_app(settings)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        async with application.router.lifespan_context(application):
            pass


async def test_ready_hides_database_errors(api):
    api.app.state.session_factory = None
    health = await api.client.get("/health")
    response = await api.client.get("/ready")
    session = await api.client.get("/api/session")
    assert health.status_code == 200
    assert health.json()["version"]
    assert response.status_code == 503
    assert response.json()["reason"] == "database"
    assert "Traceback" not in response.text
    assert session.status_code == 503
    assert session.json()["detail"] == "База сейчас недоступна. Попробуйте ещё раз."


async def test_validation_error_does_not_echo_the_body(api):
    response = await api.client.post(
        "/api/session", json={"init_data": 1, "question": "секрет ученика"}
    )
    assert response.status_code == 422
    assert "секрет ученика" not in response.text
