import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, user_from_cookie
from app.bot.service import current_lesson, student_history, student_progress, student_turn
from app.domain.messages_ru import SUBMISSION_UNAVAILABLE

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_PHOTO_BYTES = 8 * 1024 * 1024


class PracticeBody(BaseModel):
    mode: str = "training"
    text: str | None = Field(default=None, max_length=1000)
    action: str | None = Field(default=None, max_length=32)
    topic: str | None = Field(default=None, max_length=200)
    version: int | None = Field(default=None, ge=0, le=1_000_000)


def _image_kind(blob: bytes) -> str | None:
    if blob.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(blob) >= 12 and blob.startswith(b"RIFF") and blob[8:12] == b"WEBP":
        return "webp"
    if blob.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    return None


def _reject(result: dict) -> JSONResponse:
    status = 422 if result.get("code") == "empty" else 409
    return JSONResponse(
        {"detail": result.get("detail") or "Запрос отклонён", "code": result.get("code")},
        status_code=status,
    )


@router.get("/api/student/progress")
async def progress(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    student = await user_from_cookie(request, session, "student")
    return await student_progress(session, student, request.app.state.settings)


@router.get("/api/student/history")
async def history(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    student = await user_from_cookie(request, session, "student")
    return await student_history(session, student)


@router.get("/api/student/lesson")
async def lesson(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    student = await user_from_cookie(request, session, "student")
    return await current_lesson(session, student)


@router.post("/api/student/practice")
async def practice(
    body: PracticeBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    student = await user_from_cookie(request, session, "student")
    if body.mode == "submission":
        return JSONResponse(
            {"detail": SUBMISSION_UNAVAILABLE, "code": "submission_unavailable"},
            status_code=409,
        )
    if body.mode != "training":
        raise HTTPException(status_code=422, detail="Некорректный запрос")
    try:
        result = await student_turn(
            session,
            student,
            request.app.state.settings,
            request.app.state.explainer,
            text=body.text,
            action=body.action,
            topic=body.topic,
            version=body.version,
        )
        if not result.get("ok"):
            await session.rollback()
            return _reject(result)
        await session.commit()
    except HTTPException:
        raise
    except Exception as exc:
        await session.rollback()
        logger.error("practice failed: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Не получилось сохранить занятие") from None
    return result


@router.post("/api/student/practice/photo")
async def practice_photo(
    request: Request,
    photo: UploadFile = File(),
    text: str = Form(""),
    mode: str = Form("training"),
    session: AsyncSession = Depends(db_session),
) -> dict:
    student = await user_from_cookie(request, session, "student")
    if mode == "submission":
        await photo.close()
        return JSONResponse(
            {"detail": SUBMISSION_UNAVAILABLE, "code": "submission_unavailable"},
            status_code=409,
        )
    if mode != "training":
        await photo.close()
        raise HTTPException(status_code=422, detail="Некорректный запрос")
    if len(text) > 1000:
        await photo.close()
        raise HTTPException(status_code=422, detail="Слишком длинный вопрос")
    blob = await photo.read(MAX_PHOTO_BYTES + 1)
    await photo.close()
    if len(blob) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Фото больше 8 МБ")
    if _image_kind(blob) is None:
        raise HTTPException(
            status_code=415,
            detail="Нужен файл изображения: JPEG, PNG, WebP или GIF",
        )
    del blob
    try:
        result = await student_turn(
            session,
            student,
            request.app.state.settings,
            request.app.state.explainer,
            text=text,
            photo=True,
        )
        if not result.get("ok"):
            await session.rollback()
            return _reject(result)
        await session.commit()
    except HTTPException:
        raise
    except Exception as exc:
        await session.rollback()
        logger.error("practice photo failed: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Не получилось сохранить занятие") from None
    return result
