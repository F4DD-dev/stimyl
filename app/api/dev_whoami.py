"""Временная страница сверки user.id. Подключается только при DEV=true."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.security.init_data import read_init_data

router = APIRouter()

PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>whoami</title>
</head>
<body>
  <p id="out">Жду initData…</p>
  <script src="https://st.max.ru/js/max-web-app.js"></script>
  <script>
    const out = document.querySelector("#out");
    const initData = window.WebApp && window.WebApp.initData;
    if (!initData) {
      out.textContent = "Открой страницу из мини-приложения MAX.";
    } else {
      fetch("/api/dev/whoami", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({init_data: initData})
      }).then((response) => response.json()).then((data) => {
        out.textContent = data.user_id
          ? "user.id: " + data.user_id + (data.start_param ? " start_param: " + data.start_param : "")
          : (data.detail || "Не удалось проверить вход");
      });
    }
  </script>
</body>
</html>
"""


class WhoamiBody(BaseModel):
    init_data: str


@router.get("/dev/whoami", response_class=HTMLResponse)
async def whoami_page() -> HTMLResponse:
    return HTMLResponse(PAGE)


@router.post("/api/dev/whoami")
async def whoami(body: WhoamiBody, request: Request) -> dict[str, str]:
    settings = request.app.state.settings
    if not settings.max_token:
        raise HTTPException(status_code=503, detail="Бот не настроен")
    fields = read_init_data(body.init_data, settings.max_token)
    if fields is None:
        raise HTTPException(status_code=401, detail="Не удалось проверить вход")
    return fields
