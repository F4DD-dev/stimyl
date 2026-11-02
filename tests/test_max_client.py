import asyncio

import httpx

from app.api.session import launch_param
from app.max_client.base import OutboundButton
from app.max_client.client import MaxClient, _button


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


def test_open_app_button_includes_payload_and_bot_contact():
    rendered = _button(
        OutboundButton(
            "Открыть кабинет",
            "ticket_1",
            web_app="se14271630_1_bot",
            contact_id=515445879,
        )
    )
    assert rendered == {
        "type": "open_app",
        "text": "Открыть кабинет",
        "web_app": "se14271630_1_bot",
        "payload": "ticket_1",
        "contact_id": 515445879,
    }


def test_launch_param_accepts_a_hint_only_in_the_ticket_alphabet():
    assert launch_param("signed", "other") == "signed"
    assert launch_param("", "ticket_1") == "ticket_1"
    assert launch_param("", "has space") == ""
