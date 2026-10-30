import logging
from typing import Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class Explainer(Protocol):
    async def explain_topic(self, topic_title: str) -> str | None: ...

    async def explain_mistake(self, topic_title: str, hint: str) -> str | None: ...


class NullExplainer:
    async def explain_topic(self, topic_title: str) -> str | None:
        return None

    async def explain_mistake(self, topic_title: str, hint: str) -> str | None:
        return None


def topic_prompt(topic_title: str) -> str:
    return (
        f"Объясни тему школьной математики 8 класса «{topic_title}» "
        "в двух коротких предложениях. Не решай задачу ученика и не называй числовой ответ."
    )


def mistake_prompt(topic_title: str, hint: str) -> str:
    return (
        f"Тема «{topic_title}». Ученик ошибся в похожем задании. "
        f"Объясни приём в одном предложении, без числового ответа. Опора: {hint}"
    )


class QwenExplainer:
    def __init__(self, settings: Settings) -> None:
        self._base = (settings.llm_base_url or "").rstrip("/")
        self._model = settings.llm_model
        self._key = settings.llm_api_key

    async def explain_topic(self, topic_title: str) -> str | None:
        return await self._complete(topic_prompt(topic_title))

    async def explain_mistake(self, topic_title: str, hint: str) -> str | None:
        return await self._complete(mistake_prompt(topic_title, hint))

    async def _complete(self, prompt: str) -> str | None:
        headers = {}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{self._base}/chat/completions",
                    headers=headers,
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 300,
                    },
                )
            response.raise_for_status()
            payload = response.json()
            text = payload["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.error("llm explain failed: %s", type(exc).__name__)
            return None
        if not isinstance(text, str):
            return None
        cleaned = text.strip()
        return cleaned or None


def build_explainer(settings: Settings) -> Explainer:
    if settings.feature_llm and settings.llm_base_url:
        return QwenExplainer(settings)
    return NullExplainer()
