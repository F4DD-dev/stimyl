"""Аккаунты, согласия, коды входа и перенос. Состояние только в базе."""

import hashlib
import hmac
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
    ClassTeacher,
    Consent,
    Enrollment,
    LearningSession,
    LoginGuard,
    Message,
    School,
    SchoolClass,
    SignupHint,
    TeacherApplication,
    TeacherInvite,
    TopicState,
    TransferCode,
    User,
    UserSession,
    WebLoginCode,
)

BOT_PROVIDER = "max"
# user.id из initData сюда не пишется, пока документы не подтвердят равенство с user_id бота.
WEBAPP_PROVIDER = "max_webapp"
POLICY_VERSION = "2026-10-30"
CODE_TTL = timedelta(minutes=5)
CODE_ATTEMPTS = 5
CODES_PER_HOUR = 5
SESSION_IDLE = timedelta(hours=12)
SESSION_MAX = timedelta(days=7)
INVITE_TTL = timedelta(days=7)
TOUCH_EVERY = timedelta(minutes=5)


@dataclass
class JoinResult:
    found: bool
    created: bool
    title: str = ""


@dataclass
class IssuedCode:
    ok: bool
    code: str = ""
    detail: str = ""


@dataclass
class RedeemedCode:
    ok: bool
    token: str = ""
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


async def _join_row(session: AsyncSession, user: User, school_class: SchoolClass) -> JoinResult:
    if user.role != "student" or user.status != "active" or user.deleted_at is not None:
        return JoinResult(True, False, school_class.title)
    found = await session.scalar(
        select(Enrollment).where(
            Enrollment.class_id == school_class.id,
            Enrollment.user_id == user.id,
        )
    )
    if found is not None:
        return JoinResult(True, False, school_class.title)
    session.add(Enrollment(class_id=school_class.id, user_id=user.id))
    await write_audit(session, user.id, "join_class", user.id, None, str(school_class.id))
    return JoinResult(True, True, school_class.title)


async def join_by_key(session: AsyncSession, user: User, key: str) -> JoinResult:
    cleaned = key.strip().lower()
    if not cleaned:
        return JoinResult(False, False)
    school_class = await session.scalar(
        select(SchoolClass).where(func.lower(SchoolClass.join_key) == cleaned)
    )
    if school_class is None:
        return JoinResult(False, False)
    return await _join_row(session, user, school_class)


async def join_by_code(session: AsyncSession, user: User, code: str) -> JoinResult:
    school_class = await session.scalar(
        select(SchoolClass).where(SchoolClass.join_code == code.strip().upper())
    )
    if school_class is None:
        return JoinResult(False, False)
    return await _join_row(session, user, school_class)


def _short_token(text: str) -> str | None:
    cleaned = text.strip().upper()
    if " " in cleaned or not cleaned.isalnum() or not 4 <= len(cleaned) <= 16:
        return None
    return cleaned


async def issue_web_code(session: AsyncSession, user: User, settings: Settings) -> IssuedCode:
    from app.domain.account_copy import PENDING_BROWSER, WEB_DENIED, WEB_WAIT

    if user.deleted_at is not None or user.status == "blocked":
        return IssuedCode(False, detail=WEB_DENIED)
    if user.role == "student":
        return IssuedCode(False, detail=WEB_DENIED)
    if user.role == "teacher" and user.status != "active":
        return IssuedCode(False, detail=PENDING_BROWSER)
    if user.role not in {"teacher", "admin"} or user.status != "active":
        return IssuedCode(False, detail=WEB_DENIED)
    since = _now() - timedelta(hours=1)
    issued = await session.scalar(
        select(func.count())
        .select_from(WebLoginCode)
        .where(WebLoginCode.user_id == user.id, WebLoginCode.created_at >= since)
    )
    if int(issued or 0) >= CODES_PER_HOUR:
        return IssuedCode(False, detail=WEB_WAIT)
    code = f"{secrets.randbelow(1_000_000):06d}"
    session.add(
        WebLoginCode(
            user_id=user.id,
            code_hash=_digest(settings.session_secret, "web", code),
            expires_at=_now() + CODE_TTL,
            attempts=0,
            created_at=_now(),
        )
    )
    await write_audit(session, user.id, "web_code", user.id, None, None)
    return IssuedCode(True, code=code)


async def _guard(session: AsyncSession, ip: str) -> LoginGuard:
    row = await session.get(LoginGuard, ip[:64] or "unknown")
    now = _now()
    if row is None:
        row = LoginGuard(ip=ip[:64] or "unknown", failures=0, window_start=now)
        session.add(row)
        await session.flush()
        return row
    if now - _aware(row.window_start) > CODE_TTL:
        row.failures = 0
        row.window_start = now
    return row


async def redeem_web_code(
    session: AsyncSession,
    code: str,
    settings: Settings,
    ip: str,
    user_agent: str,
) -> RedeemedCode:
    from app.domain.account_copy import LOGIN_BAD, LOGIN_LIMIT, STUDENT_BROWSER

    guard = await _guard(session, ip)
    if guard.failures >= CODE_ATTEMPTS:
        return RedeemedCode(False, detail=LOGIN_LIMIT, status=429)
    cleaned = "".join(ch for ch in code.strip() if ch.isdigit())
    row = await session.scalar(
        select(WebLoginCode).where(
            WebLoginCode.code_hash == _digest(settings.session_secret, "web", cleaned)
        )
    )
    now = _now()
    if row is None or row.used_at is not None or _aware(row.expires_at) < now:
        guard.failures += 1
        if row is not None:
            row.attempts += 1
        await write_audit(session, None, "login_failed", None, ip, None)
        status = 429 if guard.failures >= CODE_ATTEMPTS else 401
        detail = LOGIN_LIMIT if status == 429 else LOGIN_BAD
        return RedeemedCode(False, detail=detail, status=status)
    user = await session.get(User, row.user_id)
    if user is None or user.deleted_at is not None or user.status != "active":
        return RedeemedCode(False, detail=LOGIN_BAD, status=403)
    if user.role not in {"teacher", "admin"}:
        return RedeemedCode(False, detail=STUDENT_BROWSER, status=403)
    row.used_at = now
    row.attempts += 1
    guard.failures = 0
    token = await open_browser_session(session, user, user_agent, ip, settings)
    await write_audit(session, user.id, "login_web", user.id, ip, None)
    return RedeemedCode(True, token=token, user=user)


async def open_browser_session(
    session: AsyncSession,
    user: User,
    user_agent: str,
    ip: str,
    settings: Settings,
) -> str:
    raw = secrets.token_urlsafe(32)
    now = _now()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=_digest(settings.session_secret, "session", raw),
            user_agent=(user_agent or "")[:200],
            ip=(ip or "")[:64],
            created_at=now,
            expires_at=now + SESSION_IDLE,
            last_seen_at=now,
        )
    )
    await touch(session, user)
    await session.flush()
    return raw


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


async def create_invite(session: AsyncSession, actor_id: int | None, settings: Settings) -> str:
    code = f"T{secrets.randbelow(1_000_000):06d}"
    now = _now()
    session.add(
        TeacherInvite(
            code_hash=_digest(settings.session_secret, "invite", code),
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
            TeacherInvite.code_hash == _digest(settings.session_secret, "invite", code.strip().upper())
        )
    )
    if row is None:
        return None
    if row.used_at is not None or _aware(row.expires_at) < _now():
        return INVITE_USED
    row.used_at = _now()
    row.used_by = user.id
    await approve_teacher(session, user.id, row.created_by)
    return INVITE_OK


async def create_transfer(session: AsyncSession, user_id: int, actor_id: int | None, settings: Settings) -> str | None:
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return None
    code = f"P{secrets.randbelow(1_000_000):06d}"
    now = _now()
    session.add(
        TransferCode(
            user_id=user.id,
            code_hash=_digest(settings.session_secret, "transfer", code),
            expires_at=now + CODE_TTL * 12,
            created_by=actor_id,
            created_at=now,
        )
    )
    await write_audit(session, actor_id, "transfer_begin", user.id, None, None)
    return code


async def claim_transfer(
    session: AsyncSession, new_user: User, code: str, settings: Settings
) -> str | None:
    from app.domain.account_copy import TRANSFER_BAD, TRANSFER_BUSY, TRANSFER_OK, TRANSFER_SELF

    row = await session.scalar(
        select(TransferCode).where(
            TransferCode.code_hash == _digest(settings.session_secret, "transfer", code.strip().upper())
        )
    )
    if row is None or row.used_at is not None or _aware(row.expires_at) < _now():
        return None if row is None else TRANSFER_BAD
    if row.user_id == new_user.id:
        return TRANSFER_SELF
    attempts = await session.scalar(
        select(func.count()).select_from(Attempt).where(Attempt.user_id == new_user.id)
    )
    if int(attempts or 0) > 0:
        return TRANSFER_BUSY
    old = await session.get(User, row.user_id)
    if old is None or old.deleted_at is not None:
        return TRANSFER_BAD
    now = _now()
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
    await write_audit(session, new_user.id, "transfer_done", old.id, None, None)
    return TRANSFER_OK


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
        join_code=f"K{secrets.randbelow(100_000):05d}",
        timezone="Europe/Moscow",
    )
    session.add(school_class)
    await session.flush()
    return school_class


def looks_like_token(text: str) -> str | None:
    return _short_token(text)
