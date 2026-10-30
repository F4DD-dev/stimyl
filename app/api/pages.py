from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.domain.account_copy import POLICY_STUB

router = APIRouter()
_WEB = Path(__file__).resolve().parents[1] / "web"


def _page(entry: str) -> HTMLResponse:
    html = (_WEB / "index.html").read_text(encoding="utf-8")
    html = html.replace('data-entry="auto"', f'data-entry="{entry}"', 1)
    return HTMLResponse(html)


@router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def root() -> HTMLResponse:
    return _page("auto")


@router.api_route("/cabinet", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def cabinet() -> HTMLResponse:
    return _page("teacher")


@router.api_route("/student", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def student() -> HTMLResponse:
    return _page("student")


@router.api_route("/privacy", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def privacy() -> HTMLResponse:
    body = (
        "<!DOCTYPE html><html lang=\"ru\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Политика</title></head><body><main>"
        f"<p>{POLICY_STUB}</p></main></body></html>"
    )
    return HTMLResponse(body)
