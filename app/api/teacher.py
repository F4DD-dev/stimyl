from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, user_from_cookie
from app.bot.service import class_report
from app.domain.drafts import build_check_draft

router = APIRouter()

MATERIAL_MISSING = (
    "Нет сохранённых фрагментов урока. "
    "Не собираю задания по параграфу и не выдумываю источник."
)
DELIVERY_MISSING = (
    "Отправка работ в MAX ещё не подключена. Черновик не сохранён и ученикам не ушёл."
)
NO_BANK = "По этой теме нет банка заданий. Не выдумываю вопросы."


class DraftBody(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=300)
    count: int = Field(ge=1, le=6)
    difficulty: Literal["easy", "normal", "hard"]
    audience: Literal["class", "selected"]
    students: list[str] = Field(default_factory=list, max_length=40)
    use_material: bool = False


async def _report(request: Request, session: AsyncSession):
    teacher = await user_from_cookie(request, session, "teacher")
    report = await class_report(session, teacher, request.app.state.settings)
    if report is None:
        raise HTTPException(status_code=403, detail="Нет доступа к классу")
    return report


def _students(report, body: DraftBody) -> list[str]:
    roster = [student.display_name for student in report.students]
    if body.audience == "class":
        return roster
    known = set(roster)
    wanted: list[str] = []
    for name in body.students:
        cleaned = name.strip()
        if len(cleaned) > 200 or cleaned not in known or cleaned in wanted:
            if cleaned not in known or len(cleaned) > 200:
                raise HTTPException(status_code=422, detail="Выберите учеников этого класса")
            continue
        wanted.append(cleaned)
    if not wanted:
        raise HTTPException(status_code=422, detail="Выберите учеников этого класса")
    return wanted


def _prepare(report, body: DraftBody) -> dict:
    if body.use_material:
        raise HTTPException(status_code=409, detail=MATERIAL_MISSING)
    titles = {topic.title for topic in report.topics}
    if body.topic not in titles:
        raise HTTPException(status_code=404, detail="Этой темы нет в программе класса")
    draft = build_check_draft(
        body.topic,
        body.goal,
        body.count,
        body.difficulty,
        body.audience,
        _students(report, body),
    )
    if draft is None:
        raise HTTPException(status_code=409, detail=NO_BANK)
    return draft


@router.get("/api/teacher/class")
async def teacher_class(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    report = await _report(request, session)
    return report.as_dict()


@router.get("/api/teacher/assignments")
async def assignments(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    await _report(request, session)
    return {
        "items": [],
        "delivery": "unavailable",
        "detail": "Назначенных работ пока нет. Отправка в MAX ещё не подключена.",
    }


@router.post("/api/teacher/drafts")
async def drafts(
    body: DraftBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    report = await _report(request, session)
    return _prepare(report, body)


@router.post("/api/teacher/assignments", status_code=501)
async def create_assignment(
    body: DraftBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> None:
    report = await _report(request, session)
    _prepare(report, body)
    raise HTTPException(status_code=501, detail=DELIVERY_MISSING)
