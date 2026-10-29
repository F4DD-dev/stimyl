from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

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
