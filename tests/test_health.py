from httpx import ASGITransport, AsyncClient

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
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert ready.status_code == 200
    assert ready.json()["status"] == "ok"


async def test_ready_hides_database_errors():
    settings = Settings(
        database_url="postgresql+asyncpg://user:leak-me-please@127.0.0.1:1/stimul",
        session_secret="session-secret",
    )
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/ready")
    assert response.status_code == 503
    assert "leak-me-please" not in response.text
    assert "Traceback" not in response.text


async def test_validation_error_does_not_echo_the_body(api):
    response = await api.client.post(
        "/api/session", json={"init_data": 1, "question": "секрет ученика"}
    )
    assert response.status_code == 422
    assert "секрет ученика" not in response.text
