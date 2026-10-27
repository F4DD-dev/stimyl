from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, user_from_cookie
from app.bot.service import class_report

router = APIRouter()


@router.get("/api/teacher/class")
async def teacher_class(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    teacher = await user_from_cookie(request, session, "teacher")
    report = await class_report(session, teacher, request.app.state.settings)
    if report is None:
        raise HTTPException(status_code=403, detail="Нет доступа к классу")
    return report.as_dict()
