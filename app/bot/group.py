"""Групповой чат класса в MAX. Бот отвечает только когда его упомянули.
Личные данные ученика в общий чат не уходят: отвечает общий разбор темы."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.updates import Incoming
from app.core.config import Settings
from app.db.models import (
    AuthIdentity,
    ClassChat,
    ClassTeacher,
    Enrollment,
    RuntimeFlag,
    SchoolClass,
    Topic,
    User,
)
from app.llm.explainer import Explainer

COOLDOWN = timedelta(seconds=5)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


async def _chat_row(session: AsyncSession, chat_id: int) -> ClassChat | None:
    return await session.scalar(
        select(ClassChat).where(ClassChat.max_chat_id == chat_id)
    )


async def _identity_user(session: AsyncSession, max_user_id: str) -> User | None:
    if not max_user_id:
        return None
    identity = await session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "max",
            AuthIdentity.external_id == max_user_id[:64],
            AuthIdentity.revoked_at.is_(None),
        )
    )
    if identity is None:
        return None
    user = await session.get(User, identity.user_id)
    if user is None or user.deleted_at is not None:
        return None
    return user


async def _class_for_user(session: AsyncSession, max_user_id: str) -> int | None:
    """Класс, к которому привязан человек: учитель — класс ведения, ученик — зачисление."""
    user = await _identity_user(session, max_user_id)
    if user is None:
        return None
    if user.role in {"teacher", "admin"}:
        return await session.scalar(
            select(ClassTeacher.class_id)
            .where(ClassTeacher.user_id == user.id)
            .order_by(ClassTeacher.class_id)
        )
    return await session.scalar(
        select(Enrollment.class_id)
        .where(Enrollment.user_id == user.id, Enrollment.status == "active")
        .order_by(Enrollment.class_id)
    )


async def _member_of_class(session: AsyncSession, max_user_id: str, class_id: int) -> bool:
    user = await _identity_user(session, max_user_id)
    if user is None:
        return False
    link = await session.scalar(
        select(ClassTeacher.user_id).where(
            ClassTeacher.class_id == class_id, ClassTeacher.user_id == user.id
        )
    )
    if link is not None:
        return True
    return (
        await session.scalar(
            select(Enrollment.user_id).where(
                Enrollment.class_id == class_id,
                Enrollment.user_id == user.id,
                Enrollment.status == "active",
            )
        )
        is not None
    )


async def _chat_title(sender: object, chat_id: int) -> str:
    getter = getattr(sender, "chat_info", None)
    if getter is None:
        return ""
    try:
        info = await getter(chat_id)
    except Exception:
        return ""
    if isinstance(info, dict):
        return str(info.get("title") or "")[:200]
    return ""


async def _chat_members(sender: object, chat_id: int) -> list[str]:
    getter = getattr(sender, "chat_members", None)
    if getter is None:
        return []
    try:
        members = await getter(chat_id)
    except Exception:
        return []
    return [str(item) for item in members or []]


async def _class_title(session: AsyncSession, class_id: int) -> str:
    return await session.scalar(
        select(SchoolClass.title).where(SchoolClass.id == class_id)
    ) or ""


async def _link(session: AsyncSession, incoming: Incoming, sender: object) -> None:
    chat_id = incoming.chat_id
    if chat_id is None:
        return
    row = await _chat_row(session, chat_id)
    if row is not None and row.active and row.class_id is not None:
        return
    class_id = await _class_for_user(session, incoming.max_user_id)
    if class_id is None:
        for member in await _chat_members(sender, chat_id):
            class_id = await _class_for_user(session, member)
            if class_id is not None:
                break
    title = await _chat_title(sender, chat_id)
    now = _now()
    if row is None:
        row = ClassChat(
            class_id=class_id,
            max_chat_id=chat_id,
            title=title,
            ai_enabled=class_id is not None,
            active=True,
            created_at=now,
        )
        session.add(row)
    else:
        if class_id is not None:
            row.class_id = class_id
            row.ai_enabled = True
        row.active = True
        if title:
            row.title = title
    await session.flush()
    if class_id is not None:
        klass = await _class_title(session, class_id)
        await sender.send_text(
            user_id="",
            chat_id=chat_id,
            text=(
                f"Стимул в классе {klass}. Задавайте вопросы с упоминанием: "
                "@имя_бота или «Стимул, …». Личный прогресс здесь не обсуждаем."
            ),
            buttons=[],
        )
    else:
        await sender.send_text(
            user_id="",
            chat_id=chat_id,
            text=(
                "Стимул на связи. Чтобы отвечать на вопросы в этом чате, меня должен "
                "добавить учитель или ученик привязанного класса — тогда я "
                "подключусь к классу сам."
            ),
            buttons=[],
        )


async def _unlink(session: AsyncSession, incoming: Incoming) -> None:
    if incoming.chat_id is None:
        return
    row = await _chat_row(session, incoming.chat_id)
    if row is not None:
        row.active = False


def _mentioned(incoming: Incoming, settings: Settings) -> bool:
    text = (incoming.text or "").strip()
    if not text:
        return False
    lowered = text.casefold()
    username = (settings.bot_username or "").strip().lstrip("@").casefold()
    if username and f"@{username}" in lowered:
        return True
    contact = int(settings.bot_contact_id or 0)
    if contact and f"max://user/{contact}" in text:
        return True
    for lead in ("стимул", "бот"):
        if lowered == lead or lowered.startswith(f"{lead},") or lowered.startswith(f"{lead} "):
            return True
    return False


async def _cooling(session: AsyncSession, chat_id: int) -> bool:
    key = f"group_cd:{chat_id}"[:64]
    row = await session.get(RuntimeFlag, key)
    now = _now()
    if row is not None:
        try:
            last = datetime.fromisoformat(row.value)
        except ValueError:
            last = now
        if now - _aware(last) < COOLDOWN:
            return True
    if row is None:
        session.add(RuntimeFlag(key=key, value=now.isoformat()))
    else:
        row.value = now.isoformat()
    return False


async def _stranger_once(session: AsyncSession, sender: object, incoming: Incoming) -> None:
    """Чужому в общем чате один раз подсказываем, что отвечаю только классу."""
    if incoming.chat_id is None:
        return
    key = f"group_stranger:{incoming.chat_id}"[:64]
    flag = await session.get(RuntimeFlag, key)
    if flag is not None:
        return
    session.add(RuntimeFlag(key=key, value="1"))
    await session.flush()
    await sender.send_text(
        user_id="",
        chat_id=incoming.chat_id,
        text="Отвечаю только участникам привязанного класса.",
        buttons=[],
    )


async def _group_context(session: AsyncSession, class_id: int) -> str:
    klass = await _class_title(session, class_id)
    titles = list(
        await session.scalars(select(Topic.title).order_by(Topic.position).limit(20))
    )
    parts = [f"Групповой чат класса {klass}. Это общий разговор: личный прогресс и данные конкретных учеников не упоминай и не обсуждай."]
    if titles:
        parts.append("Темы программы: " + ", ".join(titles) + ".")
    return "\n".join(parts)


async def process_group_update(
    session: AsyncSession,
    incoming: Incoming,
    sender: object,
    explainer: Explainer,
    settings: Settings,
) -> None:
    if incoming.kind == "bot_added":
        await _link(session, incoming, sender)
        return
    if incoming.kind == "bot_removed":
        await _unlink(session, incoming)
        return
    if incoming.kind != "group_text" or incoming.chat_id is None:
        return
    row = await _chat_row(session, incoming.chat_id)
    if (
        row is None
        or not row.active
        or row.class_id is None
        or not row.ai_enabled
    ):
        return
    if not _mentioned(incoming, settings):
        return
    if not await _member_of_class(session, incoming.max_user_id, row.class_id):
        await _stranger_once(session, sender, incoming)
        return
    if await _cooling(session, row.max_chat_id):
        return
    if not getattr(explainer, "enabled", False):
        return
    typing = getattr(sender, "typing", None)
    if typing is not None:
        await typing(row.max_chat_id)
    answer = await explainer.group_reply(
        incoming.text or "", await _group_context(session, row.class_id)
    )
    if answer:
        await sender.send_text(
            user_id="",
            chat_id=row.max_chat_id,
            text=answer,
            buttons=[],
        )
