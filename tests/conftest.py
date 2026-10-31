import os
import time
from dataclasses import dataclass

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from alembic import command
from app.core.config import Settings
from app.db.models import RuntimeFlag
from app.db.seed import seed
from app.db.session import make_engine
from app.jobs import HEARTBEAT_KEY
from app.llm.explainer import NullExplainer
from app.main import create_app
from app.max_client.base import OutboundButton

TEST_DATABASE_URL = "postgresql+asyncpg://stimul:stimul@127.0.0.1:5432/stimul"


class MemorySender:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.callbacks: list[str] = []

    async def send_text(
        self,
        *,
        user_id: str,
        chat_id: int | None,
        text: str,
        buttons: list[OutboundButton],
    ) -> None:
        self.sent.append(
            {
                "user_id": user_id,
                "chat_id": chat_id,
                "text": text,
                "buttons": [_stored_button(button) for button in buttons],
            }
        )

    async def answer_callback(
        self,
        callback_id: str,
        notification: str | None = None,
        text: str | None = None,
        buttons: list[OutboundButton] | None = None,
    ) -> bool:
        self.callbacks.append(callback_id)
        if not text and not buttons:
            return False
        self.sent.append(
            {
                "user_id": "",
                "chat_id": None,
                "text": text or "",
                "buttons": [_stored_button(button) for button in buttons or []],
            }
        )
        return True

    async def aclose(self) -> None:
        return None


def _stored_button(button: OutboundButton) -> dict[str, str]:
    return {"text": button.text, "payload": button.payload, "url": button.url}


@dataclass
class Api:
    client: AsyncClient
    memory: MemorySender
    app: object
    settings: Settings


def postgres_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or TEST_DATABASE_URL
    if url.startswith("sqlite"):
        url = TEST_DATABASE_URL
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


@pytest.fixture(scope="session")
def database_url() -> str:
    url = postgres_url()
    os.environ["DATABASE_URL"] = url
    command.upgrade(Config("alembic.ini"), "head")
    return url


async def truncate(url: str) -> None:
    engine = make_engine(url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE TABLE "
                "jobs, messages, attempts, topic_states, sessions, web_login_codes, "
                "user_sessions, consents, auth_identities, teacher_applications, "
                "teacher_invites, transfer_codes, signup_hints, login_guards, "
                "audit_log, inbound_events, runtime_flags, enrollments, class_teachers, "
                "users, topics, subjects, classes, schools "
                "RESTART IDENTITY CASCADE"
            )
        )
    await engine.dispose()


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        max_token="test-token",
        max_webhook_secret="hook-secret",
        session_secret="session-secret",
        llm_base_url=None,
        env="dev",
        dev=False,
    )


@pytest.fixture
async def api(settings: Settings, database_url: str):
    await truncate(database_url)
    application = create_app(settings)
    memory = MemorySender()
    application.state.sender = memory
    application.state.explainer = NullExplainer()
    async with application.router.lifespan_context(application):
        factory = application.state.session_factory
        async with factory() as session:
            session.add(RuntimeFlag(key=HEARTBEAT_KEY, value=str(int(time.time()))))
            await session.commit()
        transport = ASGITransport(app=application)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield Api(client=client, memory=memory, app=application, settings=settings)


@pytest.fixture
async def seeded(api: Api) -> Api:
    factory = api.app.state.session_factory
    async with factory() as session:
        await seed(session)
        await session.commit()
    return api
