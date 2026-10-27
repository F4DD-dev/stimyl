from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()
_WEB = Path(__file__).resolve().parents[1] / "web"


@router.get("/cabinet", response_class=HTMLResponse)
async def cabinet() -> HTMLResponse:
    return HTMLResponse((_WEB / "cabinet.html").read_text(encoding="utf-8"))


@router.get("/student", response_class=HTMLResponse)
async def student() -> HTMLResponse:
    return HTMLResponse((_WEB / "student.html").read_text(encoding="utf-8"))
