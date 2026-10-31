import asyncio

import httpx

from app.max_client.client import MaxClient


async def test_send_text_does_not_deadlock_on_the_rate_lock():
    client = MaxClient("token", None)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url="https://platform-api2.max.ru",
        transport=httpx.MockTransport(handler),
    )
    await asyncio.wait_for(
        client.send_text(user_id="1", chat_id=None, text="привет", buttons=[]),
        timeout=2,
    )
    await client.aclose()
