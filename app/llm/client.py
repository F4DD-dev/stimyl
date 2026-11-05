"""OpenAI-совместимый чат: OpenRouter, свой VPS или любой другой провайдер с /chat/completions."""

import asyncio
import json
import logging
import re
import time

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)

_RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class ChatClient:
    def __init__(self, settings: Settings) -> None:
        self._base = (settings.llm_base_url or "").rstrip("/")
        self._key = settings.llm_api_key
        self.model = settings.llm_model
        self.vision_model = settings.llm_vision_model or settings.llm_model
        self._timeout = settings.llm_timeout
        self._referer = settings.public_base_url or "https://stimyl.online"
        self._openrouter = "openrouter.ai" in self._base
        self._fallbacks = [
            item.strip() for item in settings.llm_fallback_models.split(",") if item.strip()
        ]

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
        body: dict[str, object] = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens * 3 if reasoning else max_tokens,
            "temperature": temperature,
        }
        if self._openrouter and self._fallbacks:
            chain = [body["model"], *[item for item in self._fallbacks if item != body["model"]]]
            body["models"] = chain[:3]
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if reasoning:
            body["reasoning"] = {"enabled": True, "exclude": True}
        headers = {
            "Content-Type": "application/json",
            "HTTP-Referer": self._referer,
            "X-Title": "Stimul",
        }
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        if time.time() < _quota["closed_until"]:
            logger.warning("llm %s skipped: daily free quota is used up", purpose)
            return None
        started = time.monotonic()
        pause = 1.5
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{self._base}/chat/completions", headers=headers, json=body
                    )
            except httpx.HTTPError as exc:
                logger.error("llm %s transport %s attempt=%s", purpose, type(exc).__name__, attempt)
                if attempt == 2:
                    return None
                await asyncio.sleep(pause)
                pause *= 2
                continue
            if response.status_code == 429 and _daily_limit(response):
                _quota["closed_until"] = _next_utc_midnight()
                logger.error("llm %s daily free quota is used up until next UTC day", purpose)
                return None
            if response.status_code in _RETRY_STATUS and attempt < 1:
                wait = _retry_after(response) or pause
                logger.warning("llm %s status=%s retry in %.1fs", purpose, response.status_code, wait)
                await asyncio.sleep(min(wait, 12))
                pause *= 2
                continue
            if response.status_code == 400 and json_mode and "response_format" in body:
                body.pop("response_format")
                continue
            if not response.is_success:
                logger.error("llm %s status=%s code=%s", purpose, response.status_code, _code(response))
                return None
            text = _content(response)
            try:
                served = response.json().get("model") or body["model"]
            except (ValueError, AttributeError):
                served = body["model"]
            logger.info(
                "llm %s ok model=%s ms=%d chars=%d",
                purpose,
                served,
                int((time.monotonic() - started) * 1000),
                len(text or ""),
            )
            return text
        return None


_quota = {"closed_until": 0.0}


def quota_closed() -> bool:
    return time.time() < _quota["closed_until"]


def _daily_limit(response: httpx.Response) -> bool:
    text = response.text.casefold()
    return "per-day" in text or "per day" in text or "daily" in text


def _next_utc_midnight() -> float:
    now = time.time()
    return now - (now % 86400) + 86400 + 60


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _code(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("code") or "")[:40]
    return ""


def _content(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("error"):
        logger.error("llm payload error code=%s", _code(response))
        return None
    try:
        content = payload["choices"][0]["message"].get("content")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str):
        return None
    return content.strip() or None


def loads_object(text: str | None) -> dict | None:
    """JSON-объект из ответа модели: снимает ```json и лишний текст вокруг."""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
