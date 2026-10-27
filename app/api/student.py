from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, user_from_cookie
from app.bot.service import student_progress

router = APIRouter()


@router.get("/api/student/progress")
async def progress(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    student = await user_from_cookie(request, session, "student")
    return await student_progress(session, student, request.app.state.settings)
