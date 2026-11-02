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
    cabinet_text,
    consent_text,
)
from app.domain.accounts import (
    BOT_PROVIDER,
    IssuedCode,
    accept_consent,
    claim_invite,
    claim_transfer,
    continue_application,
    draft_application,
    find_identity,
    issue_app_ticket,
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
from app.domain.directory import (
    application_of,
    approve,
    choose_city,
    choose_role,
    choose_school,
    choose_seat,
    city_reply,
    ensure_directory,
    pending_reply,
    placed,
    role_reply,
    school_reply,
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
    app_text: str = ""
    app_payload: str = ""
    app_name: str = ""


@dataclass
class GateOutcome:
    user: User | None
    replies: list[GateReply]
    stop: bool


def _fold(text: str) -> str:
    return text.strip().casefold().replace("ё", "е")


def _named_action(payload: str | None) -> str:
    raw = (payload or "").strip()
    if raw.startswith("v") and ":" in raw:
        head, rest = raw.split(":", 1)
        if head[1:].isdigit():
            return rest.split(":", 1)[0]
    return raw


def bot_name(settings: Settings) -> str:
    raw = (settings.bot_username or "").strip().lstrip("@")
    if raw and all(ch.isalnum() or ch in "._-" for ch in raw):
        return raw
    return ""


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
        return GateOutcome(None, [GateReply(f"user_id: {external}")], True)
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
    action = _named_action(incoming.payload)
    if action == "apps" or folded == "заявки":
        text_out, buttons = await pending_reply(session, user)
        return GateOutcome(user, [GateReply(text_out, buttons)], True)
    if action.startswith("approve:") and action.split(":", 1)[1].isdigit():
        text_out, buttons = await approve(session, user, int(action.split(":", 1)[1]))
        return GateOutcome(user, [GateReply(text_out, buttons)], True)
    if action in {WEB_LOGIN, "open_cabinet"} or folded in {"войти в кабинет", "открыть кабинет"}:
        return await _send_code(session, user, settings)
    if action == "progress" or folded == "мой прогресс":
        return await _send_app(session, user, settings)

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

    if not await placed(session, user):
        reply = await _directory(session, user, incoming, settings)
        return GateOutcome(user, replies + [reply], True)
    return GateOutcome(user, replies, False)


async def _without_account(
    session: AsyncSession, incoming: Incoming, settings: Settings
) -> GateOutcome:
    if incoming.payload == CONSENT_YES:
        user = await accept_consent(session, incoming.max_user_id, incoming.name, settings)
        text_out, buttons = role_reply()
        replies = [GateReply(text_out, buttons)]
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


async def _directory(session: AsyncSession, user: User, incoming: Incoming, settings: Settings) -> GateReply:
    await ensure_directory(session)
    action = _named_action(incoming.payload)
    allow_bootstrap = settings.env != "prod"
    row = await application_of(session, user)
    if row is not None and row.status == "pending":
        return GateReply("Заявка ещё на проверке у администратора школы. Когда примут, напиши /start.")
    if row is not None and row.status == "approved" and not await placed(session, user):
        return GateReply("Заявку приняли. Напиши /start ещё раз.")
    if action.startswith("role:"):
        text_out, buttons = await choose_role(session, user, action.split(":", 1)[1])
        return GateReply(text_out, buttons)
    if action.startswith("city:") and action.split(":", 1)[1].isdigit():
        text_out, buttons = await choose_city(session, user, int(action.split(":", 1)[1]))
        return GateReply(text_out, buttons)
    if action.startswith("school:"):
        text_out, buttons = await choose_school(
            session, user, action.split(":", 1)[1], allow_admin_bootstrap=allow_bootstrap
        )
        return GateReply(text_out, buttons)
    if action.startswith("seat:"):
        text_out, buttons = await choose_seat(
            session, user, action.split(":", 1)[1], allow_admin_bootstrap=allow_bootstrap
        )
        return GateReply(text_out, buttons)
    if row is None:
        text_out, buttons = role_reply()
        return GateReply(text_out, buttons)
    if not row.city:
        text_out, buttons = city_reply()
        return GateReply(text_out, buttons)
    if row.school_id is None:
        text_out, buttons = school_reply(row.city)
        return GateReply(text_out, buttons)
    return GateReply("Выбери себя кнопкой ниже или напиши /start.")


async def _send_code(session: AsyncSession, user: User, settings: Settings) -> GateOutcome:
    username = bot_name(settings)
    base = (settings.public_base_url or "").rstrip("/")
    link = base.startswith("http")
    if not link and not username:
        return GateOutcome(user, [GateReply("Ссылку на кабинет сейчас не собрать.")], True)
    issued: IssuedCode = await issue_web_code(session, user, settings)
    if not issued.ok:
        return GateOutcome(user, [GateReply(issued.detail)], True)
    reply = GateReply(cabinet_text())
    if username:
        reply.app_text = "Открыть кабинет"
        reply.app_payload = issued.ticket
        reply.app_name = username
    if link:
        reply.link_text = "Открыть в браузере" if username else "Открыть кабинет"
        reply.link_url = f"{base}/cabinet?ticket={issued.ticket}"
    return GateOutcome(user, [reply], True)


async def _send_app(session: AsyncSession, user: User, settings: Settings) -> GateOutcome:
    username = bot_name(settings)
    if not username:
        return GateOutcome(user, [GateReply("Кнопку в приложение сейчас не собрать.")], True)
    issued: IssuedCode = await issue_app_ticket(session, user, settings)
    if not issued.ok:
        return GateOutcome(user, [GateReply(issued.detail)], True)
    reply = GateReply("Кнопка откроет твой прогресс. Она действует 5 минут и только один раз.")
    reply.app_text = "Мой прогресс"
    reply.app_payload = issued.ticket
    reply.app_name = username
    return GateOutcome(user, [reply], True)
