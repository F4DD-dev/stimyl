"""Личные чаты с помощником: список, история и лимит запросов на пользователя."""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import AssistantChat, AssistantMessage

CHAT_KINDS = ("student", "teacher")
MAX_MESSAGES = 200
TITLE_LEN = 60


def _now() -> datetime:
    return datetime.now(UTC)


async def list_chats(
    session: AsyncSession, user_id: int, kind: str, *, limit: int = 30
) -> list[AssistantChat]:
    rows = await session.scalars(
        select(AssistantChat)
        .where(AssistantChat.user_id == user_id, AssistantChat.kind == kind)
        .order_by(AssistantChat.pinned.desc(), AssistantChat.updated_at.desc())
        .limit(limit)
    )
    return list(rows)


async def set_pinned(
    session: AsyncSession, user_id: int, kind: str, chat_id: int, pinned: bool
) -> bool:
    chat = await get_chat(session, user_id, kind, chat_id)
    if chat is None:
        return False
    chat.pinned = pinned
    return True


async def delete_chat(session: AsyncSession, user_id: int, kind: str, chat_id: int) -> bool:
    chat = await get_chat(session, user_id, kind, chat_id)
    if chat is None:
        return False
    await session.execute(
        delete(AssistantMessage).where(AssistantMessage.chat_id == chat.id)
    )
    await session.delete(chat)
    return True


async def get_chat(
    session: AsyncSession, user_id: int, kind: str, chat_id: int
) -> AssistantChat | None:
    return await session.scalar(
        select(AssistantChat).where(
            AssistantChat.id == chat_id,
            AssistantChat.user_id == user_id,
            AssistantChat.kind == kind,
        )
    )


async def create_chat(
    session: AsyncSession, user_id: int, kind: str, title: str = ""
) -> AssistantChat:
    now = _now()
    chat = AssistantChat(
        user_id=user_id,
        kind=kind,
        title=title.strip()[:TITLE_LEN],
        created_at=now,
        updated_at=now,
    )
    session.add(chat)
    await session.flush()
    return chat


async def messages_of(session: AsyncSession, chat_id: int) -> list[AssistantMessage]:
    rows = list(
        await session.scalars(
            select(AssistantMessage)
            .where(AssistantMessage.chat_id == chat_id)
            .order_by(AssistantMessage.id.desc())
            .limit(MAX_MESSAGES)
        )
    )
    return list(reversed(rows))


async def clear_messages(session: AsyncSession, chat_id: int) -> None:
    """Полный сброс истории чата — для тестов и нового диалога."""
    await session.execute(
        delete(AssistantMessage).where(AssistantMessage.chat_id == chat_id)
    )


async def add_message(
    session: AsyncSession,
    chat: AssistantChat,
    *,
    role: str,
    text: str,
    kind: str = "text",
    payload: dict | None = None,
) -> AssistantMessage:
    now = _now()
    message = AssistantMessage(
        chat_id=chat.id,
        user_id=chat.user_id,
        role=role,
        kind=kind,
        text=text[:8000],
        payload=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
        created_at=now,
    )
    session.add(message)
    chat.updated_at = now
    if role == "user" and not chat.title:
        chat.title = text.strip().replace("\n", " ")[:TITLE_LEN]
    await session.flush()
    return message


async def rate_status(
    session: AsyncSession, user_id: int, settings: Settings
) -> tuple[bool, str]:
    """Лимит сообщений пользователя в чатах помощника: в час и в сутки."""
    now = _now()
    counts = await session.execute(
        select(
            func.count()
            .filter(AssistantMessage.created_at > now - timedelta(hours=1))
            .label("hour"),
            func.count()
            .filter(AssistantMessage.created_at > now - timedelta(days=1))
            .label("day"),
        ).where(
            AssistantMessage.user_id == user_id,
            AssistantMessage.role == "user",
        )
    )
    hour, day = counts.one()
    if int(hour or 0) >= settings.assistant_msgs_per_hour:
        return False, (
            f"Слишком много вопросов за час (лимит {settings.assistant_msgs_per_hour}). "
            "Попробуйте позже или вернитесь к уроку."
        )
    if int(day or 0) >= settings.assistant_msgs_per_day:
        return False, (
            f"Дневной лимит вопросов исчерпан ({settings.assistant_msgs_per_day}). "
            "Помощник снова будет доступен завтра."
        )
    return True, ""


def chat_payload(message: AssistantMessage) -> dict | None:
    if not message.payload:
        return None
    try:
        value = json.loads(message.payload)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def chat_view(chat: AssistantChat, messages: list[AssistantMessage]) -> dict:
    return {
        "id": chat.id,
        "title": chat.title,
        "updated_at": chat.updated_at.isoformat(),
        "messages": [
            {
                "id": item.id,
                "role": item.role,
                "kind": item.kind,
                "text": item.text,
                "payload": chat_payload(item),
                "created_at": item.created_at.isoformat(),
            }
            for item in messages
        ],
    }
