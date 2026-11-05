"""Аккаунты, согласия, коды входа и перенос. Состояние только в базе."""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
    Attempt,
    AuditLog,
    AuthIdentity,
    ClassSubjectTeacher,
    ClassTeacher,
    Consent,
    Enrollment,
    JoinApplication,
    LearningSession,
    LoginGuard,
    Message,
    Notice,
    OutboundNotice,
    School,
    SchoolClass,
    SignupHint,
    StaffSeat,
    TeacherApplication,
    TeacherInvite,
    TopicState,
    TransferCode,
    User,
    UserSession,
    WebLoginCode,
    WorkAnswer,
    WorkRecipient,
)

BOT_PROVIDER = "max"
# Строка max_webapp появляется из билета в start_param или при ALLOW_ID_MATCH.
WEBAPP_PROVIDER = "max_webapp"
POLICY_VERSION = "2026-10-30"
CODE_TTL = timedelta(minutes=5)
CODE_ATTEMPTS = 5
CODES_PER_HOUR = 5
FAIL_WINDOW = timedelta(minutes=15)
USER_FAILS = 5
IP_FAILS = 30
INVITE_TTL = timedelta(days=1)
TRANSFER_TTL = timedelta(hours=1)
SESSION_IDLE = timedelta(hours=12)
SESSION_MAX = timedelta(days=7)
TOUCH_EVERY = timedelta(minutes=5)


@dataclass
class JoinResult:
    found: bool
    created: bool
    title: str = ""
    pending: bool = False
    closed: bool = False
    limited: bool = False


@dataclass
class IssuedCode:
    ok: bool
    code: str = ""
    ticket: str = ""
    public_id: str = ""
    detail: str = ""


@dataclass
class RedeemedCode:
    ok: bool
    token: str = ""
    csrf: str = ""
    user: User | None = None
    detail: str = ""
    status: int = 401


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def _digest(secret: str, kind: str, value: str) -> str:
    return hmac.new(secret.encode(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def admin_ids(settings: Settings) -> set[str]:
    return {item.strip() for item in settings.admin_max_ids.split(",") if item.strip()}


def policy_url(settings: Settings) -> str:
    base = (settings.public_base_url or "").rstrip("/")
    if base.startswith("http"):
        return f"{base}/privacy"
    return ""


async def write_audit(
    session: AsyncSession,
    actor_id: int | None,
    action: str,
    target_id: int | None,
    ip: str | None,
    detail: str | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_user_id=actor_id,
            action=action[:64],
            target_user_id=target_id,
            ip=(ip or "")[:64] or None,
            detail=(detail or "")[:300] or None,
            created_at=_now(),
        )
    )


async def find_identity(
    session: AsyncSession, provider: str, external_id: str
) -> AuthIdentity | None:
    return await session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == provider,
            AuthIdentity.external_id == external_id,
        )
    )


async def user_by_provider(
    session: AsyncSession, provider: str, external_id: str
) -> User | None:
    identity = await find_identity(session, provider, external_id)
    if identity is None or identity.revoked_at is not None:
        return None
    user = await session.get(User, identity.user_id)
    if user is None or user.deleted_at is not None:
        return None
    return user


_NAME = re.compile(r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё.'\- ]{0,79}$")


def clean_display_name(raw: str) -> str | None:
    text = " ".join((raw or "").split())
    if not _NAME.fullmatch(text) or len(text) < 2:
        return None
    return text


async def rename_once(session: AsyncSession, user: User, raw: str) -> tuple[str | None, str | None]:
    """Человек меняет своё имя сам и только один раз."""
    if user.name_changed:
        return None, "Имя можно сменить только один раз."
    cleaned = clean_display_name(raw)
    if cleaned is None:
        return None, "Имя: 2–80 букв, можно пробел и дефис."
    if cleaned == user.display_name:
        return None, "Это уже ваше имя."
    user.display_name = cleaned
    user.name_changed = True
    await session.flush()
    return cleaned, None


async def remember_payload(session: AsyncSession, external_id: str, payload: str | None) -> None:
    if not payload:
        return
    cleaned = payload.strip()[:128]
    if not cleaned:
        return
    row = await session.get(SignupHint, external_id[:64])
    if row is None:
        session.add(
            SignupHint(external_id=external_id[:64], start_payload=cleaned, updated_at=_now())
        )
        return
    row.start_payload = cleaned
    row.updated_at = _now()


async def accept_consent(
    session: AsyncSession,
    external_id: str,
    display_name: str,
    settings: Settings,
) -> User:
    """Создаёт users и auth_identities в одной транзакции. Повтор не плодит строку."""
    existing = await user_by_provider(session, BOT_PROVIDER, external_id)
    if existing is not None:
        return existing
    identity = await find_identity(session, BOT_PROVIDER, external_id)
    if identity is not None:
        found = await session.get(User, identity.user_id)
        if found is not None:
            return found
    role = "admin" if external_id in admin_ids(settings) else "student"
    now = _now()
    user = User(
        role=role,
        display_name=(display_name or "Ученик")[:200],
        status="active",
        created_at=now,
        last_seen_at=now,
    )
    try:
        async with session.begin_nested():
            session.add(user)
            await session.flush()
            session.add(
                AuthIdentity(
                    user_id=user.id,
                    provider=BOT_PROVIDER,
                    external_id=external_id[:64],
                    created_at=now,
                )
            )
            session.add(
                Consent(user_id=user.id, policy_version=POLICY_VERSION, accepted_at=now)
            )
            await session.flush()
    except IntegrityError:
        winner = await user_by_provider(session, BOT_PROVIDER, external_id)
        if winner is None:
            raise
        return winner
    await write_audit(session, user.id, "consent", user.id, None, role)
    return user


async def take_hint(session: AsyncSession, external_id: str) -> str | None:
    row = await session.get(SignupHint, external_id[:64])
    if row is None:
        return None
    payload = row.start_payload
    await session.delete(row)
    return payload


async def touch(session: AsyncSession, user: User) -> None:
    now = _now()
    seen = user.last_seen_at
    if seen is not None and now - _aware(seen) < TOUCH_EVERY:
        return
    user.last_seen_at = now


async def _join_row(
    session: AsyncSession, user: User, school_class: SchoolClass, *, needs_approval: bool
) -> JoinResult:
    if not school_class.join_open:
        return JoinResult(True, False, school_class.title, closed=True)
    if user.role != "student" or user.status != "active" or user.deleted_at is not None:
        return JoinResult(True, False, school_class.title)
    found = await session.scalar(
        select(Enrollment).where(
            Enrollment.class_id == school_class.id,
            Enrollment.user_id == user.id,
        )
    )
    if found is not None:
        return JoinResult(True, False, school_class.title, pending=found.status == "pending")
    status = "pending" if needs_approval else "active"
    session.add(Enrollment(class_id=school_class.id, user_id=user.id, status=status))
    await write_audit(session, user.id, "join_class", user.id, None, status)
    return JoinResult(True, True, school_class.title, pending=status == "pending")


async def _join_blocked(session: AsyncSession, user: User) -> bool:
    guard = await _guard(session, f"join:{user.id}", FAIL_WINDOW)
    return guard.failures >= USER_FAILS


async def _join_miss(session: AsyncSession, user: User) -> JoinResult:
    guard = await _guard(session, f"join:{user.id}", FAIL_WINDOW)
    guard.failures += 1
    if guard.failures >= USER_FAILS:
        return JoinResult(False, False, limited=True)
    return JoinResult(False, False)


async def join_by_key(
    session: AsyncSession, user: User, key: str, *, needs_approval: bool
) -> JoinResult:
    if await _join_blocked(session, user):
        return JoinResult(False, False, limited=True)
    cleaned = key.strip().lower()
    if not cleaned:
        return await _join_miss(session, user)
    school_class = await session.scalar(
        select(SchoolClass).where(func.lower(SchoolClass.join_key) == cleaned)
    )
    if school_class is None:
        return await _join_miss(session, user)
    return await _join_row(session, user, school_class, needs_approval=needs_approval)


async def join_by_code(
    session: AsyncSession, user: User, code: str, *, needs_approval: bool
) -> JoinResult:
    if await _join_blocked(session, user):
        return JoinResult(False, False, limited=True)
    school_class = await session.scalar(
        select(SchoolClass).where(SchoolClass.join_code == code.strip().upper())
    )
    if school_class is None:
        return await _join_miss(session, user)
    return await _join_row(session, user, school_class, needs_approval=needs_approval)


def _short_token(text: str) -> str | None:
    cleaned = text.strip()
    if cleaned.startswith(("T-", "P-")) and " " not in cleaned and 12 <= len(cleaned) <= 80:
        return cleaned
    upper = cleaned.upper()
    if " " in upper or not upper.isalnum() or not 4 <= len(upper) <= 16:
        return None
    return upper


async def issue_web_code(session: AsyncSession, user: User, settings: Settings) -> IssuedCode:
    return await _issue_login(session, user, settings, allow_student=False)


async def issue_app_ticket(session: AsyncSession, user: User, settings: Settings) -> IssuedCode:
    """Билет мини-приложения. Ученику тоже, лимит тот же, что у кода кабинета."""
    return await _issue_login(session, user, settings, allow_student=True)


async def _issue_login(
    session: AsyncSession,
    user: User,
    settings: Settings,
    *,
    allow_student: bool,
) -> IssuedCode:
    from app.domain.account_copy import PENDING_BROWSER, WEB_DENIED, WEB_WAIT

    if user.deleted_at is not None or user.status == "blocked":
        return IssuedCode(False, detail=WEB_DENIED)
    if user.role == "student" and not allow_student:
        return IssuedCode(False, detail=WEB_DENIED)
    if user.role == "teacher" and user.status != "active":
        return IssuedCode(False, detail=PENDING_BROWSER)
    allowed = {"teacher", "admin", "student"} if allow_student else {"teacher", "admin"}
    pending_student = allow_student and user.role == "student" and user.status == "pending"
    if not pending_student and (user.role not in allowed or user.status != "active"):
        return IssuedCode(False, detail=WEB_DENIED)
    since = _now() - timedelta(hours=1)
    issued = await session.scalar(
        select(func.count())
        .select_from(WebLoginCode)
        .where(WebLoginCode.user_id == user.id, WebLoginCode.created_at >= since)
    )
    if int(issued or 0) >= CODES_PER_HOUR:
        return IssuedCode(False, detail=WEB_WAIT)
    now = _now()
    code = await _free_code(session, settings)
    ticket = secrets.token_urlsafe(32)
    public_id = secrets.token_hex(4)
    session.add(
        WebLoginCode(
            user_id=user.id,
            code_hash=_digest(settings.session_secret, "web", code),
            token_hash=_digest(settings.session_secret, "ticket", ticket),
            public_id=public_id,
            expires_at=now + CODE_TTL,
            attempts=0,
            created_at=now,
        )
    )
    await write_audit(session, user.id, "web_code", user.id, None, None)
    return IssuedCode(True, code=code, ticket=ticket, public_id=public_id)


async def ensure_webapp_identity(session: AsyncSession, user: User, external_id: str) -> bool:
    """Привязать user.id мини-приложения. False, если этот id уже у другого человека."""
    external_id = external_id[:64]
    existing = await find_identity(session, WEBAPP_PROVIDER, external_id)
    if existing is not None and existing.revoked_at is None and existing.user_id != user.id:
        return False
    if existing is not None:
        existing.user_id = user.id
        existing.revoked_at = None
        return True
    try:
        async with session.begin_nested():
            session.add(
                AuthIdentity(
                    user_id=user.id,
                    provider=WEBAPP_PROVIDER,
                    external_id=external_id,
                    created_at=_now(),
                )
            )
            await session.flush()
    except IntegrityError:
        winner = await find_identity(session, WEBAPP_PROVIDER, external_id)
        if winner is None or winner.user_id != user.id or winner.revoked_at is not None:
            return False
    return True


async def claim_webapp_ticket(
    session: AsyncSession,
    ticket: str,
    web_user_id: str,
    settings: Settings,
) -> User | None:
    """Погасить билет и записать max_webapp в той же транзакции."""
    cleaned = ticket.strip()
    if not re.fullmatch(r"[\w-]{1,512}", cleaned):
        return None
    digest = _digest(settings.session_secret, "ticket", cleaned)
    row = await session.scalar(
        select(WebLoginCode).where(WebLoginCode.token_hash == digest).with_for_update()
    )
    now = _now()
    if row is None or row.used_at is not None or _aware(row.expires_at) < now:
        return None
    user = await session.get(User, row.user_id)
    if user is None or user.deleted_at is not None or user.status not in {"active", "pending"}:
        row.used_at = now
        return None
    bound = await ensure_webapp_identity(session, user, web_user_id)
    row.used_at = now
    action = "link_webapp" if bound else "link_webapp_conflict"
    await write_audit(session, user.id, action, user.id, None, None)
    return user if bound else None


async def _free_code(session: AsyncSession, settings: Settings) -> str:
    """Два живых кода не должны совпасть."""
    now = _now()
    for _ in range(8):
        code = f"{secrets.randbelow(1_000_000):06d}"
        digest = _digest(settings.session_secret, "web", code)
        clash = await session.scalar(
            select(WebLoginCode.id).where(
                WebLoginCode.code_hash == digest,
                WebLoginCode.used_at.is_(None),
                WebLoginCode.expires_at > now,
            )
        )
        if clash is None:
            return code
    raise RuntimeError("не удалось выдать уникальный код")


async def _guard(session: AsyncSession, key: str, window: timedelta) -> LoginGuard:
    row = await session.get(LoginGuard, key[:64] or "unknown")
    now = _now()
    if row is None:
        row = LoginGuard(ip=key[:64] or "unknown", failures=0, window_start=now)
        session.add(row)
        await session.flush()
        return row
    if now - _aware(row.window_start) > window:
        row.failures = 0
        row.window_start = now
    return row


async def _login_limited(session: AsyncSession, ip: str, user_id: int | None) -> bool:
    ip_guard = await _guard(session, ip[:64] or "unknown", FAIL_WINDOW)
    if ip_guard.failures >= IP_FAILS:
        return True
    if user_id is None:
        return False
    user_guard = await _guard(session, f"login:{user_id}", FAIL_WINDOW)
    return user_guard.failures >= USER_FAILS


async def _login_fail(session: AsyncSession, ip: str, user_id: int | None, row: WebLoginCode | None) -> None:
    ip_guard = await _guard(session, ip[:64] or "unknown", FAIL_WINDOW)
    ip_guard.failures += 1
    if user_id is not None:
        user_guard = await _guard(session, f"login:{user_id}", FAIL_WINDOW)
        user_guard.failures += 1
    if row is not None:
        row.attempts += 1
    await write_audit(session, user_id, "login_failed", user_id, ip, None)


async def redeem_web_code(
    session: AsyncSession,
    public_id: str,
    code: str,
    settings: Settings,
    ip: str,
    user_agent: str,
) -> RedeemedCode:
    from app.domain.account_copy import LOGIN_BAD, LOGIN_LIMIT, STUDENT_BROWSER

    row = await session.scalar(
        select(WebLoginCode).where(WebLoginCode.public_id == public_id.strip().lower())
    )
    user_id = row.user_id if row is not None else None
    if await _login_limited(session, ip, user_id):
        return RedeemedCode(False, detail=LOGIN_LIMIT, status=429)
    now = _now()
    cleaned = "".join(ch for ch in code.strip() if ch.isdigit())
    digest = _digest(settings.session_secret, "web", cleaned)
    expired = row is None or row.used_at is not None or _aware(row.expires_at) < now
    mismatch = row is None or row.code_hash != digest or row.attempts >= CODE_ATTEMPTS
    if expired or mismatch:
        await _login_fail(session, ip, user_id, row)
        limited = await _login_limited(session, ip, user_id)
        return RedeemedCode(
            False,
            detail=LOGIN_LIMIT if limited else LOGIN_BAD,
            status=429 if limited else 401,
        )
    user = await session.get(User, row.user_id)
    if user is None or user.deleted_at is not None or user.status != "active":
        return RedeemedCode(False, detail=LOGIN_BAD, status=403)
    if user.role not in {"teacher", "admin"}:
        return RedeemedCode(False, detail=STUDENT_BROWSER, status=403)
    row.used_at = now
    token, csrf = await open_browser_session(session, user, user_agent, ip, settings)
    await write_audit(session, user.id, "login_web", user.id, ip, None)
    return RedeemedCode(True, token=token, csrf=csrf, user=user)


async def redeem_ticket(
    session: AsyncSession,
    ticket: str,
    settings: Settings,
    ip: str,
    user_agent: str,
) -> RedeemedCode:
    from app.domain.account_copy import LOGIN_BAD, STUDENT_BROWSER

    digest = _digest(settings.session_secret, "ticket", ticket.strip())
    row = await session.scalar(select(WebLoginCode).where(WebLoginCode.token_hash == digest))
    now = _now()
    if row is None or row.used_at is not None or _aware(row.expires_at) < now:
        await _login_fail(session, ip, row.user_id if row else None, row)
        return RedeemedCode(False, detail=LOGIN_BAD, status=401)
    user = await session.get(User, row.user_id)
    if user is None or user.deleted_at is not None or user.status != "active":
        return RedeemedCode(False, detail=LOGIN_BAD, status=403)
    if user.role not in {"teacher", "admin"}:
        return RedeemedCode(False, detail=STUDENT_BROWSER, status=403)
    row.used_at = now
    token, csrf = await open_browser_session(session, user, user_agent, ip, settings)
    await write_audit(session, user.id, "login_link", user.id, ip, None)
    return RedeemedCode(True, token=token, csrf=csrf, user=user)


async def open_browser_session(
    session: AsyncSession,
    user: User,
    user_agent: str,
    ip: str,
    settings: Settings,
) -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    now = _now()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=_digest(settings.session_secret, "session", raw),
            csrf_token=csrf,
            user_agent=(user_agent or "")[:200],
            ip=(ip or "")[:64],
            created_at=now,
            expires_at=now + SESSION_IDLE,
            last_seen_at=now,
        )
    )
    await touch(session, user)
    await session.flush()
    return raw, csrf


async def user_for_token(
    session: AsyncSession, raw: str, settings: Settings
) -> tuple[User, UserSession] | None:
    if not raw:
        return None
    row = await session.scalar(
        select(UserSession).where(
            UserSession.token_hash == _digest(settings.session_secret, "session", raw)
        )
    )
    if row is None or row.revoked_at is not None:
        return None
    now = _now()
    created = _aware(row.created_at)
    if now - created > SESSION_MAX or _aware(row.expires_at) < now:
        return None
    user = await session.get(User, row.user_id)
    if user is None or user.deleted_at is not None:
        return None
    if now - _aware(row.last_seen_at) >= TOUCH_EVERY:
        row.last_seen_at = now
        row.expires_at = min(now + SESSION_IDLE, created + SESSION_MAX)
        await touch(session, user)
        await session.commit()
    return user, row


async def revoke_session(session: AsyncSession, row: UserSession) -> None:
    row.revoked_at = _now()


async def revoke_all(session: AsyncSession, user_id: int) -> None:
    await session.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )


async def list_sessions(session: AsyncSession, user_id: int) -> list[UserSession]:
    rows = await session.scalars(
        select(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .order_by(UserSession.id.desc())
    )
    now = _now()
    return [
        row
        for row in rows
        if _aware(row.expires_at) >= now and now - _aware(row.created_at) <= SESSION_MAX
    ]


async def draft_application(session: AsyncSession, user: User) -> TeacherApplication | None:
    row = await session.get(TeacherApplication, user.id)
    if row is None or row.status != "draft":
        return None
    return row


async def start_application(session: AsyncSession, user: User) -> str:
    from app.domain.account_copy import ALREADY_TEACHER, APPLY_WAIT, ASK_NAME

    if user.role in {"teacher", "admin"} and user.status == "active":
        return ALREADY_TEACHER
    row = await session.get(TeacherApplication, user.id)
    if row is not None and row.status == "pending":
        return APPLY_WAIT
    now = _now()
    if row is None:
        session.add(
            TeacherApplication(
                user_id=user.id,
                status="draft",
                created_at=now,
                updated_at=now,
            )
        )
    else:
        row.status = "draft"
        row.full_name = None
        row.school_name = None
        row.updated_at = now
    return ASK_NAME


async def continue_application(session: AsyncSession, user: User, text: str) -> str:
    from app.domain.account_copy import APPLY_CANCEL, APPLY_SENT, ASK_SCHOOL

    row = await session.get(TeacherApplication, user.id)
    if row is None or row.status != "draft":
        return ""
    cleaned = text.strip()
    if cleaned.casefold().replace("ё", "е") == "отмена":
        await session.delete(row)
        return APPLY_CANCEL
    row.updated_at = _now()
    if not row.full_name:
        row.full_name = cleaned[:200]
        return ASK_SCHOOL
    row.school_name = cleaned[:200]
    row.status = "pending"
    await write_audit(session, user.id, "teacher_apply", user.id, None, None)
    return APPLY_SENT


async def approve_teacher(session: AsyncSession, user_id: int, actor_id: int | None) -> bool:
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return False
    user.role = "teacher"
    user.status = "active"
    row = await session.get(TeacherApplication, user.id)
    if row is not None:
        row.status = "approved"
        row.updated_at = _now()
    await session.execute(delete(Enrollment).where(Enrollment.user_id == user.id))
    await revoke_all(session, user.id)
    await write_audit(session, actor_id, "approve_teacher", user.id, None, None)
    return True


async def set_blocked(session: AsyncSession, user_id: int, blocked: bool, actor_id: int | None) -> bool:
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return False
    user.status = "blocked" if blocked else "active"
    await revoke_all(session, user.id)
    await write_audit(
        session,
        actor_id,
        "block" if blocked else "unblock",
        user.id,
        None,
        None,
    )
    return True


async def close_user(session: AsyncSession, user_id: int, actor_id: int | None) -> bool:
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return False
    user.deleted_at = _now()
    await revoke_all(session, user.id)
    await write_audit(session, actor_id, "close_user", user.id, None, None)
    return True


async def delete_user_data(session: AsyncSession, user_id: int, actor_id: int | None) -> bool:
    """Полное удаление по запросу. В журнале остаётся факт без имени."""
    user = await session.get(User, user_id)
    if user is None:
        return False
    session_ids = list(
        await session.scalars(select(LearningSession.id).where(LearningSession.user_id == user_id))
    )
    if session_ids:
        await session.execute(delete(Message).where(Message.session_id.in_(session_ids)))
    await session.execute(delete(Attempt).where(Attempt.user_id == user_id))
    await session.execute(delete(TopicState).where(TopicState.user_id == user_id))
    await session.execute(delete(LearningSession).where(LearningSession.user_id == user_id))
    await session.execute(delete(Enrollment).where(Enrollment.user_id == user_id))
    await session.execute(delete(ClassTeacher).where(ClassTeacher.user_id == user_id))
    await session.execute(delete(ClassSubjectTeacher).where(ClassSubjectTeacher.user_id == user_id))
    await session.execute(delete(JoinApplication).where(JoinApplication.user_id == user_id))
    await session.execute(
        update(JoinApplication).where(JoinApplication.reviewed_by == user_id).values(reviewed_by=None)
    )
    await session.execute(update(StaffSeat).where(StaffSeat.user_id == user_id).values(user_id=None))
    await session.execute(delete(Notice).where(Notice.user_id == user_id))
    await session.execute(delete(OutboundNotice).where(OutboundNotice.user_id == user_id))
    await session.execute(delete(WorkAnswer).where(WorkAnswer.user_id == user_id))
    await session.execute(delete(WorkRecipient).where(WorkRecipient.user_id == user_id))
    await session.execute(delete(WebLoginCode).where(WebLoginCode.user_id == user_id))
    await session.execute(delete(UserSession).where(UserSession.user_id == user_id))
    await session.execute(delete(Consent).where(Consent.user_id == user_id))
    await session.execute(delete(TeacherApplication).where(TeacherApplication.user_id == user_id))
    await session.execute(delete(TransferCode).where(TransferCode.user_id == user_id))
    identities = list(
        await session.scalars(select(AuthIdentity).where(AuthIdentity.user_id == user_id))
    )
    for identity in identities:
        hint = await session.get(SignupHint, identity.external_id)
        if hint is not None:
            await session.delete(hint)
        await session.delete(identity)
    await session.execute(
        update(AuditLog).where(AuditLog.actor_user_id == user_id).values(actor_user_id=None)
    )
    await session.execute(
        update(TeacherInvite).where(TeacherInvite.created_by == user_id).values(created_by=None)
    )
    await session.execute(
        update(TeacherInvite).where(TeacherInvite.used_by == user_id).values(used_by=None)
    )
    await session.execute(
        update(TransferCode).where(TransferCode.created_by == user_id).values(created_by=None)
    )
    await write_audit(session, actor_id if actor_id != user_id else None, "delete_user", user_id, None, None)
    await session.delete(user)
    return True


def _long_secret(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(18)


async def create_invite(session: AsyncSession, actor_id: int | None, settings: Settings) -> str:
    code = _long_secret("T-")
    now = _now()
    session.add(
        TeacherInvite(
            code_hash=_digest(settings.session_secret, "invite", code),
            attempts=0,
            created_by=actor_id,
            expires_at=now + INVITE_TTL,
            created_at=now,
        )
    )
    await write_audit(session, actor_id, "invite", None, None, None)
    return code


async def claim_invite(session: AsyncSession, user: User, code: str, settings: Settings) -> str | None:
    from app.domain.account_copy import INVITE_OK, INVITE_USED

    row = await session.scalar(
        select(TeacherInvite).where(
            TeacherInvite.code_hash == _digest(settings.session_secret, "invite", code.strip())
        )
    )
    if row is None:
        return None
    if row.attempts >= CODE_ATTEMPTS or row.used_at is not None or _aware(row.expires_at) < _now():
        row.attempts += 1
        return INVITE_USED
    row.used_at = _now()
    row.used_by = user.id
    await approve_teacher(session, user.id, row.created_by)
    return INVITE_OK


async def create_transfer(session: AsyncSession, user_id: int, actor_id: int | None, settings: Settings) -> str | None:
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return None
    code = _long_secret("P-")
    now = _now()
    session.add(
        TransferCode(
            user_id=user.id,
            code_hash=_digest(settings.session_secret, "transfer", code),
            attempts=0,
            expires_at=now + TRANSFER_TTL,
            created_by=actor_id,
            created_at=now,
        )
    )
    await write_audit(session, actor_id, "transfer_begin", user.id, None, None)
    return code


async def claim_transfer(
    session: AsyncSession, new_user: User, code: str, settings: Settings
) -> str | None:
    from app.domain.account_copy import TRANSFER_BAD, TRANSFER_OK, TRANSFER_SELF

    row = await session.scalar(
        select(TransferCode).where(
            TransferCode.code_hash == _digest(settings.session_secret, "transfer", code.strip())
        )
    )
    if row is None:
        return None
    if row.attempts >= CODE_ATTEMPTS or row.used_at is not None or _aware(row.expires_at) < _now():
        row.attempts += 1
        return TRANSFER_BAD
    if row.user_id == new_user.id:
        return TRANSFER_SELF
    old = await session.get(User, row.user_id)
    if old is None or old.deleted_at is not None:
        return TRANSFER_BAD
    now = _now()
    await _merge_into(session, new_user, old)
    await session.execute(
        update(AuthIdentity)
        .where(AuthIdentity.user_id == old.id, AuthIdentity.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await session.execute(
        update(AuthIdentity)
        .where(AuthIdentity.user_id == new_user.id)
        .values(user_id=old.id, revoked_at=None)
    )
    await revoke_all(session, old.id)
    await revoke_all(session, new_user.id)
    new_user.deleted_at = now
    row.used_at = now
    await write_audit(session, new_user.id, "transfer_done", old.id, None, "merged")
    return TRANSFER_OK


async def _merge_into(session: AsyncSession, new_user: User, old: User) -> None:
    """История нового профиля переезжает на старый users.id, оболочка нового закрывается."""
    await session.execute(
        update(Attempt).where(Attempt.user_id == new_user.id).values(user_id=old.id)
    )
    await session.execute(
        update(LearningSession).where(LearningSession.user_id == new_user.id).values(user_id=old.id)
    )
    fresh_states = list(
        await session.scalars(select(TopicState).where(TopicState.user_id == new_user.id))
    )
    for state in fresh_states:
        kept = await session.scalar(
            select(TopicState).where(
                TopicState.user_id == old.id,
                TopicState.topic_id == state.topic_id,
            )
        )
        if kept is None:
            state.user_id = old.id
        else:
            await session.delete(state)
    await session.execute(delete(Enrollment).where(Enrollment.user_id == new_user.id))


async def add_school(session: AsyncSession, title: str) -> School:
    school = School(title=title.strip()[:200], created_at=_now())
    session.add(school)
    await session.flush()
    return school


async def add_class(session: AsyncSession, school_id: int, title: str) -> SchoolClass | None:
    school = await session.get(School, school_id)
    if school is None:
        return None
    suffix = secrets.token_hex(4)
    school_class = SchoolClass(
        school_id=school.id,
        title=title.strip()[:64],
        join_key=f"c-{suffix}",
        join_code=secrets.token_hex(4).upper(),
        join_open=True,
        timezone="Europe/Moscow",
    )
    session.add(school_class)
    await session.flush()
    return school_class


def looks_like_token(text: str) -> str | None:
    return _short_token(text)


async def approve_enrollment(session: AsyncSession, teacher_id: int, student_id: int) -> bool:
    class_ids = list(
        await session.scalars(select(ClassTeacher.class_id).where(ClassTeacher.user_id == teacher_id))
    )
    if not class_ids:
        return False
    row = await session.scalar(
        select(Enrollment).where(
            Enrollment.user_id == student_id,
            Enrollment.class_id.in_(class_ids),
            Enrollment.status == "pending",
        )
    )
    if row is None:
        return False
    row.status = "active"
    student = await session.get(User, student_id)
    if student is not None and student.status == "pending":
        student.status = "active"
    await write_audit(session, teacher_id, "approve_join", student_id, None, str(row.class_id))
    return True


async def rotate_class_key(session: AsyncSession, teacher_id: int, class_id: int) -> SchoolClass | None:
    owns = await session.scalar(
        select(ClassTeacher).where(
            ClassTeacher.user_id == teacher_id,
            ClassTeacher.class_id == class_id,
        )
    )
    if owns is None:
        return None
    school_class = await session.get(SchoolClass, class_id)
    if school_class is None:
        return None
    school_class.join_key = "k-" + secrets.token_hex(8)
    school_class.join_code = secrets.token_hex(4).upper()
    school_class.join_open = True
    await write_audit(session, teacher_id, "rotate_key", None, None, str(class_id))
    return school_class


async def set_class_join(session: AsyncSession, teacher_id: int, class_id: int, opened: bool) -> bool:
    owns = await session.scalar(
        select(ClassTeacher).where(
            ClassTeacher.user_id == teacher_id,
            ClassTeacher.class_id == class_id,
        )
    )
    if owns is None:
        return False
    school_class = await session.get(SchoolClass, class_id)
    if school_class is None:
        return False
    school_class.join_open = opened
    await write_audit(session, teacher_id, "join_open" if opened else "join_close", None, None, str(class_id))
    return True
