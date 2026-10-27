import asyncio

from app.core.config import get_settings
from app.max_client.client import MaxClient


async def subscribe() -> None:
    settings = get_settings()
    if not settings.max_webhook_url:
        return
    if not settings.max_token or not settings.max_webhook_secret:
        raise SystemExit("MAX_TOKEN and MAX_WEBHOOK_SECRET are required")
    client = MaxClient(settings.max_token, settings.resolved_ca_path())
    try:
        await client.subscribe(settings.max_webhook_url, settings.max_webhook_secret)
    finally:
        await client.aclose()


def main() -> None:
    asyncio.run(subscribe())


if __name__ == "__main__":
    main()
