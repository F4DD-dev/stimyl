import asyncio
import logging
import ssl

import httpx

from app.max_client.base import OutboundButton

logger = logging.getLogger(__name__)

API_BASE = "https://platform-api2.max.ru"
TEXT_LIMIT = 4000


class MaxClient:
    def __init__(self, token: str, ca_path: str | None) -> None:
        context = ssl.create_default_context()
        if ca_path:
            context.load_verify_locations(cafile=ca_path)
        self._client = httpx.AsyncClient(
            base_url=API_BASE,
            headers={"Authorization": token},
            verify=context,
            timeout=30,
        )
        self._lock = asyncio.Lock()

    async def send_text(
        self,
        *,
        user_id: str,
        chat_id: int | None,
        text: str,
        buttons: list[OutboundButton],
    ) -> None:
        params: dict[str, object] = (
            {"chat_id": chat_id} if chat_id is not None else {"user_id": int(user_id)}
        )
        attachment = None
        if buttons:
            attachment = [
                {
                    "type": "inline_keyboard",
                    "payload": {
                        "buttons": [
                            [{"type": "callback", "text": button.text, "payload": button.payload}]
                            for button in buttons
                        ]
                    },
                }
            ]
        parts = _chunks(text)
        async with self._lock:
            for index, part in enumerate(parts):
                body: dict[str, object] = {"text": part}
                if attachment is not None and index == len(parts) - 1:
                    body["attachments"] = attachment
                await self._post("/messages", params=params, json=body)

    async def answer_callback(
        self,
        callback_id: str,
        notification: str | None = None,
        text: str | None = None,
    ) -> bool:
        """Подтвердить нажатие. text заменяет сообщение с кнопкой. False — не удалось."""
        body: dict[str, object] = {}
        if text:
            body["message"] = {"text": text[:TEXT_LIMIT]}
        if notification:
            body["notification"] = notification[:180]
        if not body:
            body["notification"] = "Готово"
        try:
            async with self._lock:
                await self._post("/answers", params={"callback_id": callback_id}, json=body)
        except Exception as exc:
            logger.error("callback answer failed: %s", type(exc).__name__)
            return False
        return True

    async def subscribe(self, url: str, secret: str | None) -> None:
        body: dict[str, object] = {
            "url": url,
            "update_types": ["message_created", "message_callback", "bot_started"],
        }
        if secret:
            body["secret"] = secret
        async with self._lock:
            await self._request("POST", "/subscriptions", json=body)

    async def set_commands(self, commands: list[dict[str, str]]) -> None:
        async with self._lock:
            await self._request("PATCH", "/me/commands", json={"commands": commands})

    async def get_updates(self, marker: int | None, timeout: int = 30) -> dict:
        params: dict[str, object] = {
            "limit": 50,
            "timeout": timeout,
            "types": "message_created,message_callback,bot_started",
        }
        if marker is not None:
            params["marker"] = marker
        async with self._lock:
            response = await self._client.get("/updates", params=params, timeout=timeout + 5)
        _raise_for_status(response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("max updates payload is not an object")
        return payload

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, *, params: dict, json: dict) -> None:
        await self._request("POST", path, params=params, json=json)

    async def _request(self, method: str, path: str, **kwargs: object) -> None:
        response = await self._client.request(method, path, **kwargs)
        _raise_for_status(response)


def _raise_for_status(response: httpx.Response) -> None:
    if response.is_success:
        return
    logger.error("max api failed status=%s code=%s", response.status_code, _error_code(response))
    response.raise_for_status()


def _error_code(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        return ""
    if isinstance(payload, dict) and isinstance(payload.get("code"), str):
        return payload["code"][:80]
    return ""


def _chunks(text: str, size: int = TEXT_LIMIT) -> list[str]:
    if len(text) <= size:
        return [text or " "]
    return [text[index : index + size] for index in range(0, len(text), size)]
