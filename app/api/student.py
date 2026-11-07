import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session, user_from_cookie
from app.bot.service import current_lesson, student_history, student_progress, student_turn
from app.domain import chats as chat_store
from app.domain.images import image_kind
from app.domain.messages_ru import SUBMISSION_UNAVAILABLE

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_PHOTO_BYTES = 8 * 1024 * 1024
KIND = "student"

_LESSON_PAYLOAD_KEYS = (
    "topic",
    "explanation",
    "example",
    "task",
    "feedback",
    "correct",
    "given",
    "status_line",
    "notice",
    "awaiting_answer",
    "photo_note",
)


class PracticeBody(BaseModel):
    mode: str = "training"
    text: str | None = Field(default=None, max_length=1000)
    action: str | None = Field(default=None, max_length=32)
    topic: str | None = Field(default=None, max_length=200)
    version: int | None = Field(default=None, ge=0, le=1_000_000)


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
    if image_kind(blob) is None:
        raise HTTPException(
            status_code=415,
            detail="Нужен файл изображения: JPEG, PNG, WebP или GIF",
        )
    try:
        result = await student_turn(
            session,
            student,
            request.app.state.settings,
            request.app.state.explainer,
            text=text,
            photo=blob,
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


class ChatBody(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    chat_id: int | None = Field(default=None, ge=1)


class ChatCreateBody(BaseModel):
    title: str = Field(default="", max_length=200)


def _rate_reject(detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail, "code": "rate_limited"}, status_code=429)


async def _owned_chat(
    session: AsyncSession, student, chat_id: int
):
    chat = await chat_store.get_chat(session, student.id, KIND, chat_id)
    if chat is None:
        raise HTTPException(status_code=404, detail="Чат не найден")
    return chat


async def _chat_or_create(
    session: AsyncSession, student, chat_id: int | None
):
    if chat_id is not None:
        return await _owned_chat(session, student, chat_id)
    return await chat_store.create_chat(session, student.id, KIND)


@router.get("/api/student/chats")
async def chats(
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    student = await user_from_cookie(request, session, "student")
    items = await chat_store.list_chats(session, student.id, KIND)
    return {
        "items": [
            {
                "id": chat.id,
                "title": chat.title,
                "pinned": chat.pinned,
                "updated_at": chat.updated_at.isoformat(),
            }
            for chat in items
        ]
    }


@router.post("/api/student/chats")
async def create_chat(
    body: ChatCreateBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    student = await user_from_cookie(request, session, "student")
    chat = await chat_store.create_chat(session, student.id, KIND, body.title)
    await session.commit()
    return {"id": chat.id, "title": chat.title}


@router.get("/api/student/chats/{chat_id}")
async def chat_messages(
    chat_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    student = await user_from_cookie(request, session, "student")
    chat = await _owned_chat(session, student, chat_id)
    return chat_store.chat_view(chat, await chat_store.messages_of(session, chat.id))


async def _student_chat_turn(
    session: AsyncSession,
    student,
    request: Request,
    chat,
    *,
    text: str | None,
    photo: bytes | None,
) -> JSONResponse | dict:
    settings = request.app.state.settings
    allowed, detail = await chat_store.rate_status(session, student.id, settings)
    if not allowed:
        return _rate_reject(detail)
    cleaned = (text or "").strip()
    if not cleaned and photo is None:
        return _reject({"code": "empty", "detail": "Напишите вопрос или прикрепите фото."})
    await chat_store.add_message(
        session, chat, role="user", text=cleaned or "[фото]", kind="text"
    )
    try:
        result = await student_turn(
            session,
            student,
            settings,
            request.app.state.explainer,
            text=cleaned or None,
            photo=photo,
        )
        if not result.get("ok"):
            await session.rollback()
            return _reject(result)
        payload = {key: result.get(key) for key in _LESSON_PAYLOAD_KEYS}
        payload["mode"] = result.get("mode")
        payload["step"] = result.get("step")
        summary = (result.get("explanation") or result.get("notice") or "Разбор готов.")[:500]
        await chat_store.add_message(
            session,
            chat,
            role="assistant",
            kind="lesson",
            text=summary,
            payload=payload,
        )
        await session.commit()
    except HTTPException:
        raise
    except Exception as exc:
        await session.rollback()
        logger.error("assistant chat failed: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Не получилось сохранить ответ") from None
    return {
        "ok": True,
        "chat_id": chat.id,
        "reply": result,
        "messages": chat_store.chat_view(
            chat, await chat_store.messages_of(session, chat.id)
        )["messages"],
    }


@router.post("/api/student/chats/{chat_id}/pin")
async def chat_pin(
    chat_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    """Закрепить или открепить разговор."""
    student = await user_from_cookie(request, session, "student")
    chat = await _owned_chat(session, student, chat_id)
    chat.pinned = not chat.pinned
    await session.commit()
    return {"ok": True, "pinned": chat.pinned}


@router.delete("/api/student/chats/{chat_id}")
async def chat_delete(
    chat_id: int,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    """Удалить разговор со всей историей."""
    student = await user_from_cookie(request, session, "student")
    chat = await _owned_chat(session, student, chat_id)
    await chat_store.clear_messages(session, chat.id)
    await session.delete(chat)
    await session.commit()
    return {"ok": True}


@router.post("/api/student/chats/{chat_id}/messages")
async def chat_message(
    chat_id: int,
    body: ChatBody,
    request: Request,
    session: AsyncSession = Depends(db_session),
) -> dict:
    student = await user_from_cookie(request, session, "student")
    chat = await _owned_chat(session, student, chat_id)
    return await _student_chat_turn(
        session, student, request, chat, text=body.text, photo=None
    )


@router.post("/api/student/chats/{chat_id}/messages/photo")
async def chat_message_photo(
    chat_id: int,
    request: Request,
    photo: UploadFile = File(),
    text: str = Form(""),
    session: AsyncSession = Depends(db_session),
) -> dict:
    student = await user_from_cookie(request, session, "student")
    chat = await _owned_chat(session, student, chat_id)
    if len(text) > 1000:
        await photo.close()
        raise HTTPException(status_code=422, detail="Слишком длинный вопрос")
    blob = await photo.read(MAX_PHOTO_BYTES + 1)
    await photo.close()
    if len(blob) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Фото больше 8 МБ")
    if image_kind(blob) is None:
        raise HTTPException(
            status_code=415,
            detail="Нужен файл изображения: JPEG, PNG, WebP или GIF",
        )
    return await _student_chat_turn(
        session, student, request, chat, text=text, photo=blob
    )


