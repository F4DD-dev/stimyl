import asyncio
import logging
import ssl
import time

import httpx

from app.max_client.base import OutboundButton

logger = logging.getLogger(__name__)

API_BASE = "https://platform-api2.max.ru"
TEXT_LIMIT = 4000
MIN_GAP_SECONDS = 1 / 30


class DeliveryBlocked(Exception):
    """Пользователь закрыл бота или чат удалён. Повторять нельзя."""


class DeliveryRetry(Exception):
    """Лимит MAX. Задачу можно повторить позже."""


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
        self._next_at = 0.0

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
        attachment = [_keyboard(buttons)] if buttons else None
        parts = _chunks(text)
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
        buttons: list[OutboundButton] | None = None,
    ) -> bool:
        """Подтвердить нажатие. text заменяет сообщение, кнопки остаются в нём."""
        body: dict[str, object] = {}
        if text or buttons:
            message: dict[str, object] = {}
            if text:
                message["text"] = text[:TEXT_LIMIT]
            if buttons:
                message["attachments"] = [_keyboard(buttons)]
            body["message"] = message
        if notification:
            body["notification"] = notification[:180]
        if not body:
            body["notification"] = "Готово"
        try:
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
        await self._request("POST", "/subscriptions", json=body)

    async def set_commands(self, commands: list[dict[str, str]]) -> None:
        await self._request("PATCH", "/me/commands", json={"commands": commands})

    async def my_username(self) -> str:
        """Публичное имя бота для кнопки open_app. Пусто, если MAX не ответил."""
        try:
            response = await self._client.get("/me")
            _raise_for_status(response)
            payload = response.json()
        except Exception as exc:
            logger.error("bot profile failed: %s", type(exc).__name__)
            return ""
        user = payload.get("user") if isinstance(payload, dict) else None
        if not isinstance(user, dict):
            user = payload if isinstance(payload, dict) else {}
        return str(user.get("username") or "").strip().lstrip("@")

    async def get_updates(self, marker: int | None, timeout: int = 30) -> dict:
        params: dict[str, object] = {
            "limit": 50,
            "timeout": timeout,
            "types": "message_created,message_callback,bot_started",
        }
        if marker is not None:
            params["marker"] = marker
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
        delay = 1.0
        for _ in range(4):
            await self._slot()
            response = await self._client.request(method, path, **kwargs)
            if response.status_code == 429:
                retry_after = response.headers.get("retry-after")
                try:
                    pause = float(retry_after) if retry_after else delay
                except ValueError:
                    pause = delay
                await asyncio.sleep(min(pause, 30))
                delay = min(delay * 2, 30)
                continue
            if response.status_code in {403, 404} and path in {"/messages", "/answers"}:
                raise DeliveryBlocked(_error_code(response) or str(response.status_code))
            _raise_for_status(response)
            return
        raise DeliveryRetry("429")

    async def _slot(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                if now >= self._next_at:
                    self._next_at = now + MIN_GAP_SECONDS
                    return
                pause = self._next_at - now
            await asyncio.sleep(pause)


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


def _keyboard(buttons: list[OutboundButton]) -> dict[str, object]:
    return {
        "type": "inline_keyboard",
        "payload": {"buttons": [[_button(button)] for button in buttons]},
    }


def _button(button: OutboundButton) -> dict[str, str]:
    if button.web_app:
        rendered = {"type": "open_app", "text": button.text, "web_app": button.web_app}
        if button.payload:
            rendered["payload"] = button.payload
        return rendered
    if button.url:
        return {"type": "link", "text": button.text, "url": button.url}
    return {"type": "callback", "text": button.text, "payload": button.payload}


def _chunks(text: str, size: int = TEXT_LIMIT) -> list[str]:
    if len(text) <= size:
        return [text or " "]
    return [text[index : index + size] for index in range(0, len(text), size)]
