import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from tests.conftest import Api


def sign_init_data(user_id: int, token: str, first_name: str = "Марина") -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "test-query",
        "user": json.dumps(
            {"id": user_id, "first_name": first_name},
            separators=(",", ":"),
            ensure_ascii=False,
        ),
    }
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def message(user_id: int, name: str, text: str, mid: str, images: list | None = None) -> dict:
    body: dict = {"mid": mid, "seq": 1, "text": text}
    if images is not None:
        body["attachments"] = images
    return {
        "update_type": "message_created",
        "timestamp": 1710000000000,
        "user_locale": "ru",
        "message": {
            "sender": {
                "user_id": user_id,
                "first_name": name,
                "is_bot": False,
                "last_activity_time": 1710000000000,
            },
            "recipient": {"chat_id": 7000 + user_id, "chat_type": "dialog", "user_id": user_id},
            "timestamp": 1710000000000,
            "body": body,
        },
    }


def callback(user_id: int, name: str, callback_id: str, payload: str) -> dict:
    return {
        "update_type": "message_callback",
        "timestamp": 1710000000001,
        "callback": {
            "timestamp": 1710000000001,
            "callback_id": callback_id,
            "payload": payload,
            "user": {"user_id": user_id, "first_name": name, "is_bot": False},
        },
        "message": {
            "recipient": {"chat_id": 7000 + user_id, "chat_type": "dialog", "user_id": user_id},
            "timestamp": 1710000000000,
            "body": {"mid": f"mid-{callback_id}", "seq": 1, "text": ""},
        },
        "user_locale": "ru",
    }


async def post_update(api: Api, payload: dict):
    response = await api.client.post(
        "/webhook",
        json=payload,
        headers={"X-Max-Bot-Api-Secret": api.settings.max_webhook_secret or ""},
    )
    assert response.status_code == 200, response.text
    return response


def button_payload(api: Api, label: str) -> str:
    buttons = api.memory.sent[-1]["buttons"]
    for text, payload in buttons:
        if text == label:
            return payload
    raise AssertionError(buttons)
