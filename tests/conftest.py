import os
from dataclasses import dataclass

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient

from alembic import command
from app.core.config import Settings
from app.db.seed import seed
from app.llm.explainer import NullExplainer
from app.main import create_app
from app.max_client.base import OutboundButton


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
                "buttons": [(button.text, button.payload) for button in buttons],
            }
        )

    async def answer_callback(self, callback_id: str, notification: str | None = None) -> None:
        self.callbacks.append(callback_id)

    async def aclose(self) -> None:
        return None


@dataclass
class Api:
    client: AsyncClient
    memory: MemorySender
    app: object
    settings: Settings


@pytest.fixture
def database_url(tmp_path) -> str:
    path = (tmp_path / "stimul.db").resolve().as_posix()
    url = f"sqlite+aiosqlite:///{path}"
    os.environ["DATABASE_URL"] = url
    command.upgrade(Config("alembic.ini"), "head")
    return url


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        max_token="test-token",
        max_webhook_secret="hook-secret",
        session_secret="session-secret",
        llm_base_url=None,
    )


@pytest.fixture
async def api(settings: Settings):
    application = create_app(settings)
    memory = MemorySender()
    application.state.sender = memory
    application.state.explainer = NullExplainer()
    async with application.router.lifespan_context(application):
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
