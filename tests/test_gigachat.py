import base64
import json
import logging
import time

import httpx

from app.core.config import Settings
from app.llm.explainer import LlmTutor, NullExplainer, build_explainer
from app.llm.gigachat import GigaChatClient

_SECRET = "test-basic-key"
_PNG = base64.b64encode(b"fake-png").decode()


def make_settings(**overrides) -> Settings:
    values = {
        "llm_base_url": "https://api.giga.chat/v1",
        "llm_api_key": _SECRET,
        "llm_model": "GigaChat-3-Pro",
        "llm_vision_model": "GigaChat-2-Max",
    }
    values.update(overrides)
    return Settings(**values)


def _ok_chat() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "готово"},
                    "finish_reason": "stop",
                }
            ]
        },
    )


def _ok_oauth(requests: list) -> httpx.Response:
    count = sum(1 for r in requests if r.url.path.endswith("oauth"))
    return httpx.Response(
        200,
        json={
            "access_token": f"token-{count}",
            "expires_at": int(time.time() * 1000) + 1_800_000,
        },
    )


def make_client(requests: list, handler=None, **overrides) -> GigaChatClient:
    def default(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("oauth"):
            return _ok_oauth(requests)
        if request.url.path.endswith("/files"):
            return httpx.Response(200, json={"id": "file-1"})
        if request.url.path.endswith("chat/completions"):
            return _ok_chat()
        return httpx.Response(404)

    return GigaChatClient(
        make_settings(**overrides), transport=httpx.MockTransport(handler or default)
    )


async def test_token_cached_between_chats():
    requests: list = []
    client = make_client(requests)
    assert await client.chat([{"role": "user", "content": "hi"}]) == "готово"
    assert await client.chat([{"role": "user", "content": "hi"}]) == "готово"
    oauth = [r for r in requests if r.url.path.endswith("oauth")]
    assert len(oauth) == 1
    assert oauth[0].headers["content-type"] == "application/x-www-form-urlencoded"
    assert oauth[0].headers["authorization"].startswith("Basic ")
    assert b"scope=GIGACHAT_API_PERS" in oauth[0].content
    chats = [r for r in requests if r.url.path.endswith("chat/completions")]
    assert chats[0].headers["authorization"] == "Bearer token-1"


async def test_token_refreshes_on_401():
    requests: list = []
    failed = {"done": False}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("oauth"):
            return _ok_oauth(requests)
        if request.url.path.endswith("chat/completions") and not failed["done"]:
            failed["done"] = True
            return httpx.Response(401, json={"error": "unauthorized"})
        return _ok_chat()

    client = make_client(requests, handler=handler)
    assert await client.chat([{"role": "user", "content": "hi"}]) == "готово"
    oauth = [r for r in requests if r.url.path.endswith("oauth")]
    assert len(oauth) == 2
    chats = [r for r in requests if r.url.path.endswith("chat/completions")]
    assert chats[-1].headers["authorization"] == "Bearer token-2"


async def test_expired_token_refetched():
    requests: list = []
    client = make_client(requests)
    assert await client.chat([{"role": "user", "content": "hi"}]) == "готово"
    client._token_until = time.time() - 1
    assert await client.chat([{"role": "user", "content": "hi"}]) == "готово"
    oauth = [r for r in requests if r.url.path.endswith("oauth")]
    assert len(oauth) == 2


async def test_image_message_uploads_attachment():
    requests: list = []
    client = make_client(requests)
    text = await client.chat(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Что на снимке?"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{_PNG}"},
                    },
                ],
            }
        ],
        model="GigaChat-2-Max",
        purpose="photo",
    )
    assert text == "готово"
    files = [r for r in requests if r.url.path.endswith("/files")]
    assert len(files) == 1
    chat = [r for r in requests if r.url.path.endswith("chat/completions")][-1]
    body = json.loads(chat.content)
    assert body["model"] == "GigaChat-2-Max"
    assert body["messages"][0]["content"] == "Что на снимке?"
    assert body["messages"][0]["attachments"] == ["file-1"]


async def test_oauth_failure_returns_none(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("oauth"):
            return httpx.Response(500, text="denied")
        return httpx.Response(500, text="err")

    client = make_client([], handler=handler)
    with caplog.at_level(logging.ERROR):
        assert await client.chat([{"role": "user", "content": "hi"}]) is None
    assert _SECRET not in caplog.text


def test_explainer_picks_gigachat():
    tutor = build_explainer(make_settings())
    assert isinstance(tutor, LlmTutor)
    assert isinstance(tutor._chat, GigaChatClient)


def test_explainer_off_without_key_or_base():
    assert isinstance(build_explainer(make_settings(llm_api_key="")), NullExplainer)
    assert isinstance(build_explainer(make_settings(llm_base_url="")), NullExplainer)


def test_explainer_openrouter_still_supported():
    tutor = build_explainer(
        make_settings(
            llm_base_url="https://openrouter.ai/api/v1",
            llm_api_key="sk-or",
            llm_model="google/gemma-4-31b-it:free",
        )
    )
    assert isinstance(tutor, LlmTutor)
    assert not isinstance(tutor._chat, GigaChatClient)
