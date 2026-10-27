import asyncio

from app.core.config import get_settings
from app.max_client.client import MaxClient

COMMANDS = [{"name": "start", "description": "Начать разбор"}]


async def publish() -> None:
    settings = get_settings()
    if not settings.max_token:
        raise SystemExit("MAX_TOKEN is required")
    client = MaxClient(settings.max_token, settings.resolved_ca_path())
    try:
        await client.set_commands(COMMANDS)
    finally:
        await client.aclose()


def main() -> None:
    asyncio.run(publish())


if __name__ == "__main__":
    main()
