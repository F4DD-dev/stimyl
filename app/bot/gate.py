"""Вход в бота: согласие, роль, класс. Дальше учебный сценарий не идёт, пока нет пользователя."""

import logging
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
    remember_payload,
    start_application,
    touch,
)
from app.domain.directory import (
    application_of,
    choose_city,
    choose_class,
    choose_role,
    choose_school,
    ensure_directory,
    placed,
    role_reply,
    school_reply,
)
from app.domain.messages_ru import DISCLAIMER
from app.domain.onboarding import (
    accept_claim,
    place_in_prototype,
    register_phone,
    reject_claim,
    reviewer_name,
)
from app.domain.phone import normalize_phone, phone_from_vcard, verify_contact_hash
from app.domain.school_admin import bot_applications, bot_my_class, bot_students

logger = logging.getLogger(__name__)

CONSENT_YES = "consent_yes"
CONSENT_NO_PAYLOAD = "consent_no"
WEB_LOGIN = "web_login"
PICK_TEACHER = "pick:teacher"
PICK_STUDENT = "pick:student"

ROLE_PROMPT = (
    "Привет! Выбери, кто ты:\n\n"
    "• Учитель — видит карту тем класса и кому нужна помощь, отправляет "
    "проверки выбранным ученикам. Личные вопросы и переписку учеников не видит.\n"
    "• Ученик — присылает вопрос текстом или фото страницы, получает объяснение, "
    "пример и короткую практику. Видит только свой прогресс."
)
ROLE_BUTTONS = (("Я учитель", PICK_TEACHER), ("Я ученик", PICK_STUDENT))

INTRO_TEXT = (
    "Привет! Я Стимул — твой умный ИИ-помощник. Я помогаю учителям мгновенно "
    "создавать тесты и следить за успеваемостью, а ученикам — практиковаться "
    "и научиться щелкать сложные темы как орешки. Назначенные учителем задания "
    "будут приходить прямо здесь!"
)


@dataclass
class GateReply:
    text: str
    buttons: tuple[tuple[str, str], ...] = ()
    link_text: str = ""
    link_url: str = ""
    app_text: str = ""
    app_payload: str = ""
    app_name: str = ""
    app_contact: int = 0
    request_contact: bool = False


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
    if user.phone_hash is None:
        phone = await _phone_gate(session, user, incoming, settings)
        return GateOutcome(user, phone.replies, True)
    account_token = looks_like_token(incoming.text or "") if incoming.kind == "text" else None
    if account_token and account_token.startswith("P-"):
        reply = await claim_transfer(session, user, account_token, settings)
        if reply:
            return GateOutcome(user, [GateReply(reply)], True)
    if account_token and account_token.startswith("T-"):
        reply = await claim_invite(session, user, account_token, settings)
        if reply:
            return GateOutcome(user, [GateReply(reply)], True)
    if not await placed(session, user):
        return await _placement(session, user, incoming, settings)
    if incoming.payload == CONSENT_YES:
        return GateOutcome(user, [GateReply(ALREADY)], True)

    text = incoming.text or ""
    folded = _fold(text)
    action = _named_action(incoming.payload)
    if action == "apps" or folded == "заявки":
        text_out, buttons = await bot_applications(session, user)
        return GateOutcome(user, [GateReply(text_out, buttons)], True)
    if action == "students" or folded == "ученики":
        return GateOutcome(user, [GateReply(await bot_students(session, user))], True)
    if action == "my_class" or folded == "мой класс":
        text_out, buttons = await bot_my_class(session, user)
        return GateOutcome(user, [GateReply(text_out, buttons)], True)
    if action.startswith("approve:") and action.split(":", 1)[1].isdigit():
        target_id = int(action.split(":", 1)[1])
        ok, detail = await accept_claim(session, user, target_id)
        text_out = f"Принял {detail}. Ученик получит сообщение в MAX." if ok else detail
        follow_text, buttons = await bot_applications(session, user)
        return GateOutcome(user, [GateReply(text_out), GateReply(follow_text, buttons)], True)
    if action.startswith("reject:") and action.split(":", 1)[1].isdigit():
        target_id = int(action.split(":", 1)[1])
        ok, detail = await reject_claim(session, user, target_id)
        text_out = f"Отклонил {detail}. Ученик получит сообщение в MAX." if ok else detail
        follow_text, buttons = await bot_applications(session, user)
        return GateOutcome(user, [GateReply(text_out), GateReply(follow_text, buttons)], True)
    if action in {WEB_LOGIN, "open_cabinet"} or folded in {"войти в кабинет", "открыть кабинет"}:
        return await _send_code(session, user, settings)
    if action.startswith("open_work:"):
        return await _send_app(
            session,
            user,
            settings,
            label="Открыть задание",
            lead="Кнопка откроет задание. Она действует 5 минут и только один раз.",
        )
    if action == "progress" or folded == "мой прогресс":
        return await _send_app(session, user, settings)

    if folded == "я учитель" and await placed(session, user):
        reply = await start_application(session, user)
        return GateOutcome(user, [GateReply(reply)], True)

    if incoming.kind == "text" and await draft_application(session, user) is not None:
        reply = await continue_application(session, user, text)
        if reply:
            return GateOutcome(user, [GateReply(reply)], True)

    replies: list[GateReply] = []
    if account_token and user.role == "student" and not account_token.startswith(("T-", "P-")):
        joined = await join_by_code(
            session, user, account_token, needs_approval=settings.class_join_requires_approval
        )
        reply = _join_reply(joined, unknown=True)
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

    if incoming.kind == "contact" or not await placed(session, user):
        phone = await _phone_gate(session, user, incoming, settings)
        return GateOutcome(user, replies + phone.replies, True)
    return GateOutcome(user, replies, False)


async def _without_account(
    session: AsyncSession, incoming: Incoming, settings: Settings
) -> GateOutcome:
    """Первое касание бота: роль → класс 8Б → приветствие. Без школы и города."""
    action = _named_action(incoming.payload)
    if action in {PICK_TEACHER, PICK_STUDENT}:
        return await _role_pick(session, incoming, settings, action == PICK_TEACHER)
    if incoming.payload == CONSENT_YES:
        user = await accept_consent(session, incoming.max_user_id, incoming.name, settings)
        replies = [
            GateReply(
                "Стимул на связи. Сначала подтверди номер кнопкой ниже: так учитель увидит заявку."
            ),
            _ask_phone(),
        ]
        return GateOutcome(user, replies, True)
    if incoming.payload == CONSENT_NO_PAYLOAD:
        return GateOutcome(None, [GateReply(CONSENT_NO)], True)
    return GateOutcome(None, [GateReply(ROLE_PROMPT, ROLE_BUTTONS)], True)


async def _role_pick(
    session: AsyncSession, incoming: Incoming, settings: Settings, teacher: bool
) -> GateOutcome:
    user = await accept_consent(session, incoming.max_user_id, incoming.name, settings)
    await place_in_prototype(session, user, "teacher" if teacher else "student")
    await touch(session, user)
    replies = [GateReply(f"{INTRO_TEXT}\n\n{DISCLAIMER}")]
    if user.phone_hash is None:
        replies.append(_ask_phone())
    elif teacher:
        opened = await _send_code(session, user, settings)
        replies.extend(opened.replies)
    else:
        opened = await _send_app(session, user, settings)
        replies.extend(opened.replies)
    return GateOutcome(user, replies, True)


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


async def _placement(
    session: AsyncSession, user: User, incoming: Incoming, settings: Settings
) -> GateOutcome:
    """Школа и класс до кабинета. Пока заявку не приняли, учёба не начинается."""
    action = _named_action(incoming.payload)
    row = await application_of(session, user)
    picking = action.startswith(("role:", "city:", "school:", "class:")) or row is None or row.status in {
        "draft",
        "rejected",
    }
    if picking:
        await ensure_directory(session)
    if action.startswith("role:"):
        text, buttons = await choose_role(session, user, action.split(":", 1)[1])
        return GateOutcome(user, [GateReply(text, buttons)], True)
    if action.startswith("city:") and action.split(":", 1)[1].isdigit():
        text, buttons = await choose_city(session, user, int(action.split(":", 1)[1]))
        return GateOutcome(user, [GateReply(text, buttons)], True)
    if action.startswith("school:"):
        text, buttons = await choose_school(
            session,
            user,
            action.split(":", 1)[1],
            allow_admin_bootstrap=False,
        )
        return GateOutcome(user, [GateReply(text, buttons)], True)
    if action.startswith("class:") and action.split(":", 1)[1].isdigit():
        text, buttons = await choose_class(session, user, int(action.split(":", 1)[1]), settings)
        replies = [GateReply(text, buttons)]
        row = await application_of(session, user)
        if row is not None and row.status == "pending":
            opened = await _send_app(session, user, settings, label="Открыть кабинет", lead=text)
            if opened.replies and opened.replies[0].app_payload:
                replies = opened.replies
            else:
                replies = [GateReply(text)]
        return GateOutcome(user, replies, True)
    if action in {WEB_LOGIN, "open_cabinet", "progress"} or _fold(incoming.text or "") in {
        "войти в кабинет",
        "открыть кабинет",
        "мой прогресс",
    }:
        row = await application_of(session, user)
        if row is not None and row.status == "pending":
            return await _send_app(
                session,
                user,
                settings,
                label="Открыть кабинет",
                lead="Кнопка откроет кабинет. Заявка ещё ждёт решения, заданий пока нет.",
            )
        if user.role in {"teacher", "admin"}:
            return await _send_code(session, user, settings)
    row = await application_of(session, user)
    if row is not None and row.status == "pending":
        return GateOutcome(
            user,
            [
                GateReply(
                    "Заявка уже отправлена. Открой кабинет и подожди, пока её примут.",
                    (("Открыть кабинет", "progress"),),
                )
            ],
            True,
        )
    if row is not None and row.status == "rejected":
        text, buttons = role_reply()
        return GateOutcome(
            user,
            [GateReply("Заявку отклонили. Выбери школу и класс снова."), GateReply(text, buttons)],
            True,
        )
    if row is not None and row.status == "draft" and row.school_id and not row.class_id:
        from app.db.models import School

        school = await session.get(School, row.school_id)
        if school is not None and school.external_key:
            text, buttons = await choose_school(
                session,
                user,
                school.external_key,
                allow_admin_bootstrap=False,
            )
            return GateOutcome(user, [GateReply(text, buttons)], True)
    if row is not None and row.status == "draft" and row.city and not row.school_id:
        text, buttons = school_reply(row.city)
        return GateOutcome(user, [GateReply(text, buttons)], True)
    text, buttons = role_reply()
    return GateOutcome(user, [GateReply(text, buttons)], True)


def _ask_phone() -> GateReply:
    return GateReply(
        "Нажми «Поделиться номером». Номер текстом и пересланную карточку не принимаю.",
        request_contact=True,
    )


def _looks_like_phone(text: str) -> bool:
    digits = "".join(ch for ch in text if ch.isdigit())
    return len(digits) >= 10 and len(text.strip()) <= 24


async def _phone_gate(
    session: AsyncSession, user: User, incoming: Incoming, settings: Settings
) -> GateOutcome:
    if incoming.kind != "contact":
        if user.phone_hash:
            row = await application_of(session, user)
            if row is not None and row.status == "pending":
                name = await reviewer_name(session)
                if name:
                    waiting = f"Заявка отправлена. Её смотрит {name}."
                else:
                    waiting = (
                        "Заявка записана. Ответственный учитель ещё не назначен, "
                        "принять её пока некому."
                    )
                return GateOutcome(user, [GateReply(waiting)], True)
            if row is not None and row.status == "rejected":
                return GateOutcome(
                    user,
                    [GateReply("Заявку отклонили. Если это ошибка, напиши учителю.")],
                    True,
                )
        if incoming.kind == "text" and _looks_like_phone(incoming.text or ""):
            return GateOutcome(
                user,
                [GateReply("Номер текстом не принимаю. Нажми «Поделиться номером».", request_contact=True)],
                True,
            )
        return GateOutcome(user, [_ask_phone()], True)

    vcf = incoming.contact_vcf or ""
    digest = incoming.contact_hash or ""
    token = settings.max_token or ""
    if not verify_contact_hash(vcf, digest, token):
        return GateOutcome(
            user,
            [GateReply("Контакт не подтверждён. Нажми «Поделиться номером» ещё раз.", request_contact=True)],
            True,
        )
    digits = normalize_phone(phone_from_vcard(vcf) or "")
    if digits is None:
        return GateOutcome(
            user,
            [GateReply("В контакте нет номера. Нажми «Поделиться номером» ещё раз.", request_contact=True)],
            True,
        )
    result = await register_phone(session, user, digits, settings)
    replies = [GateReply(result.text)]
    if result.ok and result.kind == "choose":
        text, buttons = role_reply()
        replies.append(GateReply(text, buttons))
        return GateOutcome(user, replies, True)
    if result.ok and result.kind == "teacher":
        cabinet = await _send_code(session, user, settings)
        return GateOutcome(user, replies + cabinet.replies, True)
    if result.ok and result.kind == "known" and user.role == "teacher" and user.status == "active":
        cabinet = await _send_code(session, user, settings)
        return GateOutcome(user, replies + cabinet.replies, True)
    if result.ok and user.role == "student" and user.status == "active":
        opened = await _send_app(session, user, settings)
        return GateOutcome(user, replies + opened.replies, True)
    return GateOutcome(user, replies, True)


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
    contact_id = int(settings.bot_contact_id or 0)
    if username and contact_id:
        reply.app_text = "Открыть кабинет"
        reply.app_payload = issued.ticket
        reply.app_name = username
        reply.app_contact = contact_id
    elif not link:
        logger.warning("open_app skipped contact_id missing")
        return GateOutcome(user, [GateReply("Кнопку в приложение сейчас не собрать.")], True)
    elif username:
        logger.warning("open_app skipped contact_id missing")
    if link:
        reply.link_text = "Открыть в браузере" if username else "Открыть кабинет"
        reply.link_url = f"{base}/cabinet?ticket={issued.ticket}"
    return GateOutcome(user, [reply], True)


async def _send_app(
    session: AsyncSession,
    user: User,
    settings: Settings,
    *,
    label: str = "Мой прогресс",
    lead: str | None = None,
) -> GateOutcome:
    username = bot_name(settings)
    if not username:
        return GateOutcome(user, [GateReply("Кнопку в приложение сейчас не собрать.")], True)
    issued: IssuedCode = await issue_app_ticket(session, user, settings)
    if not issued.ok:
        return GateOutcome(user, [GateReply(issued.detail)], True)
    contact_id = int(settings.bot_contact_id or 0)
    if not contact_id:
        logger.warning("open_app skipped contact_id missing")
        return GateOutcome(user, [GateReply("Кнопку в приложение сейчас не собрать.")], True)
    reply = GateReply(lead or "Кнопка откроет твой прогресс. Она действует 5 минут и только один раз.")
    reply.app_text = label
    reply.app_payload = issued.ticket
    reply.app_name = username
    reply.app_contact = contact_id
    return GateOutcome(user, [reply], True)
