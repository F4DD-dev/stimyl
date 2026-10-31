from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.domain.account_copy import POLICY_STUB

router = APIRouter()
_WEB = Path(__file__).resolve().parents[1] / "web"


def _bot_attr(name: str | None) -> str:
    raw = (name or "").strip().lstrip("@")
    return "".join(ch for ch in raw if ch.isalnum() or ch in "._-")


def _page(entry: str, bot_name: str | None) -> HTMLResponse:
    html = (_WEB / "index.html").read_text(encoding="utf-8")
    html = html.replace('data-entry="auto"', f'data-entry="{entry}"', 1)
    html = html.replace('data-bot=""', f'data-bot="{_bot_attr(bot_name)}"', 1)
    return HTMLResponse(html)


def _bot_name(request: Request) -> str | None:
    return getattr(request.app.state.settings, "bot_username", None)


@router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    return _page("auto", _bot_name(request))


@router.api_route("/cabinet", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def cabinet(request: Request) -> HTMLResponse:
    return _page("teacher", _bot_name(request))


@router.api_route("/student", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def student(request: Request) -> HTMLResponse:
    return _page("student", _bot_name(request))


@router.api_route("/privacy", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def privacy() -> HTMLResponse:
    body = (
        "<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Политика</title></head><body><main>"
        f"<p>{POLICY_STUB}</p></main></body></html>"
    )
    return HTMLResponse(body)
