"""GigaChat Сбера: Basic-ключ даёт access_token на 30 минут, чат — OpenAI-подобный.
Ответ считается тем же парсером, что и у прочих провайдеров (app.llm.client)."""

import asyncio
import base64
import logging
import ssl
import time
import uuid

import httpx

from app.core.config import Settings
from app.llm.client import _RETRY_STATUS, _code, _content, _edge

logger = logging.getLogger(__name__)

_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
_API_URL = "https://api.giga.chat/v1"
_TOKEN_REFRESH_AHEAD = 60.0

_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


class GigaChatClient:
    """Тот же интерфейс, что у ChatClient: model, vision_model, chat()."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self._key = settings.llm_api_key or ""
        self._scope = settings.gigachat_scope
        self._base = (settings.llm_base_url or _API_URL).rstrip("/")
        self.model = settings.llm_model
        self.vision_model = settings.llm_vision_model or self.model
        self._timeout = settings.llm_timeout
        context = ssl.create_default_context()
        ca_path = settings.resolved_ca_path()
        if ca_path:
            context.load_verify_locations(cafile=ca_path)
        self._verify = context
        self._transport = transport
        self._token = ""
        self._token_until = 0.0
        self._lock = asyncio.Lock()

    def _client(self, timeout: float) -> httpx.AsyncClient:
        if self._transport is not None:
            return httpx.AsyncClient(timeout=timeout, transport=self._transport)
        return httpx.AsyncClient(timeout=timeout, verify=self._verify)

    async def _access_token(self) -> str | None:
        async with self._lock:
            if self._token and time.time() < self._token_until - _TOKEN_REFRESH_AHEAD:
                return self._token
            try:
                async with self._client(timeout=30) as client:
                    response = await client.post(
                        _AUTH_URL,
                        headers={
                            "Authorization": f"Basic {self._key}",
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Accept": "application/json",
                            "RqUID": str(uuid.uuid4()),
                        },
                        data={"scope": self._scope},
                    )
            except httpx.HTTPError as exc:
                logger.error("gigachat oauth transport %s", type(exc).__name__)
                return None
            if response.status_code != 200:
                logger.error("gigachat oauth status=%s", response.status_code)
                return None
            try:
                payload = response.json()
                token = str(payload["access_token"])
            except (ValueError, KeyError, TypeError):
                logger.error("gigachat oauth bad payload")
                return None
            self._token = token
            expires_ms = payload.get("expires_at")
            self._token_until = float(expires_ms) / 1000 if expires_ms else time.time() + 1500
            return self._token

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        json_mode: bool = False,
        reasoning: bool = False,
        max_tokens: int = 900,
        temperature: float = 0.3,
        purpose: str = "chat",
    ) -> str | None:
        token = await self._access_token()
        if not token:
            return None
        body: dict[str, object] = {
            "model": model or self.model,
            "messages": await self._prepare(messages, token),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        started = time.monotonic()
        pause = 1.5
        for attempt in range(3):
            try:
                async with self._client(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{self._base}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        },
                        json=body,
                    )
            except httpx.HTTPError as exc:
                logger.error(
                    "gigachat %s transport %s attempt=%s", purpose, type(exc).__name__, attempt
                )
                if attempt == 2:
                    return None
                await asyncio.sleep(pause)
                pause *= 2
                continue
            if response.status_code == 401 and attempt < 2:
                self._token_until = 0.0
                token = await self._access_token()
                if not token:
                    return None
                continue
            if response.status_code in _RETRY_STATUS and attempt < 1:
                logger.warning(
                    "gigachat %s status=%s retry in %.1fs", purpose, response.status_code, pause
                )
                await asyncio.sleep(min(pause, 12))
                pause *= 2
                continue
            if response.status_code >= 400:
                logger.error(
                    "gigachat %s status=%s code=%s edge=%s",
                    purpose,
                    response.status_code,
                    _code(response),
                    _edge(response),
                )
                return None
            text = _content(response)
            logger.info(
                "gigachat %s ok model=%s ms=%d chars=%d",
                purpose,
                body["model"],
                int((time.monotonic() - started) * 1000),
                len(text or ""),
            )
            return text
        return None

    async def _prepare(self, messages: list[dict], token: str) -> list[dict]:
        """Картинки в OpenAI-формате — загрузкой в /v1/files и полем attachments."""
        prepared: list[dict] = []
        for message in messages:
            content = message.get("content")
            if not isinstance(content, list):
                prepared.append({"role": message.get("role", "user"), "content": content})
                continue
            texts = [
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            item: dict[str, object] = {
                "role": message.get("role", "user"),
                "content": "\n".join(text for text in texts if text),
            }
            attachments: list[str] = []
            for part in content:
                if not isinstance(part, dict) or part.get("type") != "image_url":
                    continue
                url = (part.get("image_url") or {}).get("url", "")
                file_id = await self._upload(token, url)
                if file_id:
                    attachments.append(file_id)
            if attachments:
                item["attachments"] = attachments
            prepared.append(item)
        return prepared

    async def _upload(self, token: str, data_url: str) -> str | None:
        header, _, encoded = data_url.partition(",")
        mime = header.removeprefix("data:").removesuffix(";base64") or "image/jpeg"
        try:
            blob = base64.b64decode(encoded)
        except ValueError:
            return None
        name = "photo." + _EXT.get(mime, "bin")
        try:
            async with self._client(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base}/files",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    data={"purpose": "general"},
                    files={"file": (name, blob, mime)},
                )
        except httpx.HTTPError as exc:
            logger.error("gigachat upload transport %s", type(exc).__name__)
            return None
        if response.status_code != 200:
            logger.error("gigachat upload status=%s", response.status_code)
            return None
        try:
            file_id = str(response.json().get("id") or "")
        except ValueError:
            file_id = ""
        return file_id or None
