"""Вход в бота: согласие, роль, класс. Дальше учебный сценарий не идёт, пока нет пользователя."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.updates import Incoming
from app.core.config import Settings
from app.db.models import User
from app.domain.account_copy import (
    ALREADY,
    BLOCKED,
    CLOSED,
    CONSENT_NO,
    JOIN_CLOSED,
    JOIN_LIMIT,
    JOIN_PENDING,
    JOIN_UNKNOWN,
    JOINED,
    UNLINKED,
    WELCOME,
    cabinet_text,
    consent_text,
)
from app.domain.accounts import (
    BOT_PROVIDER,
    IssuedCode,
    accept_consent,
    admin_ids,
    claim_invite,
    claim_transfer,
    continue_application,
    draft_application,
    find_identity,
    issue_web_code,
    join_by_code,
    join_by_key,
    looks_like_token,
    policy_url,
    remember_payload,
    start_application,
    take_hint,
    touch,
)

CONSENT_YES = "consent_yes"
CONSENT_NO_PAYLOAD = "consent_no"
WEB_LOGIN = "web_login"


@dataclass
class GateReply:
    text: str
    buttons: tuple[tuple[str, str], ...] = ()
    link_text: str = ""
    link_url: str = ""


@dataclass
class GateOutcome:
    user: User | None
    replies: list[GateReply]
    stop: bool


def _fold(text: str) -> str:
    return text.strip().casefold().replace("ё", "е")


def _consent_reply(settings: Settings) -> GateReply:
    return GateReply(
        consent_text(policy_url(settings)),
        (("Согласен", CONSENT_YES), ("Не сейчас", CONSENT_NO_PAYLOAD)),
    )


async def open_gate(
    session: AsyncSession, incoming: Incoming, settings: Settings
) -> GateOutcome:
    external = incoming.max_user_id
    command = (incoming.text or "").strip()
    if command.lower().startswith("/whoami"):
        if settings.env == "prod":
            return GateOutcome(None, [GateReply("Команда недоступна.")], True)
        if settings.dev or external in admin_ids(settings):
            return GateOutcome(None, [GateReply(f"user_id: {external}")], True)
        return GateOutcome(None, [GateReply("Команда только для администратора.")], True)
    if incoming.start_payload:
        await remember_payload(session, external, incoming.start_payload)

    identity = await find_identity(session, BOT_PROVIDER, external)
    if identity is None:
        return await _without_account(session, incoming, settings)
    if identity.revoked_at is not None:
        return GateOutcome(None, [GateReply(UNLINKED)], True)

    user = await session.get(User, identity.user_id)
    if user is None or user.deleted_at is not None:
        return GateOutcome(None, [GateReply(CLOSED)], True)
    if user.status == "blocked":
        return GateOutcome(user, [GateReply(BLOCKED)], True)

    await touch(session, user)
    if incoming.payload == CONSENT_YES:
        return GateOutcome(user, [GateReply(ALREADY)], True)

    text = incoming.text or ""
    folded = _fold(text)
    if incoming.payload == WEB_LOGIN or folded == "войти в кабинет":
        return await _send_code(session, user, settings)

    if folded == "я учитель":
        reply = await start_application(session, user)
        return GateOutcome(user, [GateReply(reply)], True)

    if incoming.kind == "text" and await draft_application(session, user) is not None:
        reply = await continue_application(session, user, text)
        if reply:
            return GateOutcome(user, [GateReply(reply)], True)

    token = looks_like_token(text) if incoming.kind == "text" else None
    if token and token.startswith("P-"):
        reply = await claim_transfer(session, user, token, settings)
        if reply:
            return GateOutcome(user, [GateReply(reply)], True)
    if token and token.startswith("T-"):
        reply = await claim_invite(session, user, token, settings)
        if reply:
            return GateOutcome(user, [GateReply(reply)], True)

    replies: list[GateReply] = []
    if token and not token.startswith(("T-", "P-")):
        joined = await join_by_code(
            session, user, token, needs_approval=settings.class_join_requires_approval
        )
        reply = _join_reply(joined, unknown=not token.startswith(("T-", "P-")))
        if reply is not None:
            return GateOutcome(user, [GateReply(reply)], True)

    if incoming.start_payload and user.role == "student":
        joined = await join_by_key(
            session,
            user,
            incoming.start_payload,
            needs_approval=settings.class_join_requires_approval,
        )
        reply = _join_reply(joined, unknown=True)
        if reply:
            replies.append(GateReply(reply))

    if incoming.kind == "start" and user.role in {"teacher", "admin"} and user.status == "active":
        replies.append(
            GateReply("Кабинет: нажми кнопку, пришлю код.", (("Войти в кабинет", WEB_LOGIN),))
        )
        return GateOutcome(user, replies, True)
    return GateOutcome(user, replies, False)


async def _without_account(
    session: AsyncSession, incoming: Incoming, settings: Settings
) -> GateOutcome:
    if incoming.payload == CONSENT_YES:
        user = await accept_consent(session, incoming.max_user_id, incoming.name, settings)
        replies = [GateReply(WELCOME)]
        payload = await take_hint(session, incoming.max_user_id)
        if payload:
            joined = await join_by_key(
                session,
                user,
                payload,
                needs_approval=settings.class_join_requires_approval,
            )
            reply = _join_reply(joined, unknown=True)
            if reply:
                replies.append(GateReply(reply))
        return GateOutcome(user, replies, True)
    if incoming.payload == CONSENT_NO_PAYLOAD:
        return GateOutcome(None, [GateReply(CONSENT_NO)], True)
    return GateOutcome(None, [_consent_reply(settings)], True)


def _join_reply(joined, *, unknown: bool) -> str | None:
    if joined.limited:
        return JOIN_LIMIT
    if joined.closed:
        return JOIN_CLOSED
    if joined.created and joined.pending:
        return JOIN_PENDING.format(title=joined.title)
    if joined.created:
        return JOINED.format(title=joined.title)
    if not joined.found and unknown:
        return JOIN_UNKNOWN
    return None


async def _send_code(session: AsyncSession, user: User, settings: Settings) -> GateOutcome:
    issued: IssuedCode = await issue_web_code(session, user, settings)
    if not issued.ok:
        return GateOutcome(user, [GateReply(issued.detail)], True)
    base = (settings.public_base_url or "").rstrip("/")
    url = f"{base}/cabinet?ticket={issued.ticket}" if base else ""
    reply = GateReply(cabinet_text(url, issued.public_id, issued.code))
    if url:
        reply.link_text = "Открыть кабинет"
        reply.link_url = url
    return GateOutcome(user, [reply], True)
