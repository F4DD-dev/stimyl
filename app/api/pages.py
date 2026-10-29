from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()
_WEB = Path(__file__).resolve().parents[1] / "web"
_TEST_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Стимул</title>
</head>
<body>
  <h1>Стимул на связи</h1>
  <p>Тест мини-приложения.</p>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
@router.get("/cabinet", response_class=HTMLResponse)
async def cabinet() -> HTMLResponse:
    return HTMLResponse(_TEST_PAGE)


@router.get("/student", response_class=HTMLResponse)
async def student() -> HTMLResponse:
    return HTMLResponse((_WEB / "student.html").read_text(encoding="utf-8"))
