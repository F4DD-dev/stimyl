"""Первый учитель и заявки учеников. Победителя определяет строка-флаг, не число пользователей."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
    AuditLog,
    AuthIdentity,
    ClassSubjectTeacher,
    ClassTeacher,
    Enrollment,
    JoinApplication,
    Notice,
    OutboundNotice,
    RuntimeFlag,
    School,
    SchoolClass,
    Subject,
    User,
)
from app.db.seed import seed_topics
from app.domain.directory import placed
from app.domain.phone import hash_phone, mask_phone

BOOTSTRAP_KEY = "prototype_bootstrap"
CLASS_TITLE = "8Б"
SUBJECT_TITLE = "Математика"


@dataclass(frozen=True)
class PhoneOutcome:
    ok: bool
    kind: str
    text: str


def bootstrap_enabled(settings: Settings) -> bool:
    return settings.env != "prod" and bool(settings.first_teacher_bootstrap)


async def prototype_class(session: AsyncSession) -> SchoolClass | None:
    """8Б демо или тестовой школы, не одноимённый класс из списка учреждений."""
    return await session.scalar(
        select(SchoolClass)
        .join(School, School.id == SchoolClass.school_id)
        .where(SchoolClass.title == CLASS_TITLE, School.external_key.is_(None))
        .order_by(SchoolClass.id)
    )


async def ensure_prototype(session: AsyncSession) -> tuple[SchoolClass, Subject]:
    """Класс 8Б и математика. Повтор ничего не дублирует и людей не создаёт."""
    await seed_topics(session)
    subject = await session.scalar(select(Subject).where(Subject.title == SUBJECT_TITLE))
    if subject is None:
        raise RuntimeError("subject missing")
    school_class = await prototype_class(session)
    if school_class is not None:
        return school_class, subject
    school = await session.scalar(select(School).order_by(School.id))
    now = datetime.now(UTC)
    if school is None:
        school = School(title="Тестовая школа", created_at=now)
        session.add(school)
        await session.flush()
    school_class = SchoolClass(
        school_id=school.id,
        title=CLASS_TITLE,
        join_key="prototype-8b",
        join_code="8BDEMO",
        join_open=True,
        timezone="Asia/Vladivostok",
    )
    session.add(school_class)
    await session.flush()
    return school_class, subject


async def register_phone(
    session: AsyncSession,
    user: User,
    digits: str,
    settings: Settings,
) -> PhoneOutcome:
    digest = hash_phone(settings.session_secret, digits)
    taken = await session.scalar(
        select(User.id).where(User.phone_hash == digest, User.id != user.id)
    )
    if taken is not None:
        return PhoneOutcome(False, "duplicate", "Этот номер уже подтверждён у другого человека.")

    await session.execute(
        text(
            "INSERT INTO runtime_flags (key, value) VALUES (:key, 'open') "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"key": BOOTSTRAP_KEY},
    )
    flag = await session.scalar(
        select(RuntimeFlag).where(RuntimeFlag.key == BOOTSTRAP_KEY).with_for_update()
    )
    if flag is None:
        return PhoneOutcome(False, "bad", "Не получилось записать регистрацию. Попробуй ещё раз.")

    try:
        async with session.begin_nested():
            user.phone_hash = digest
            user.phone_mask = mask_phone(digits)
            await session.flush()
    except IntegrityError:
        user.phone_hash = None
        user.phone_mask = None
        return PhoneOutcome(False, "duplicate", "Этот номер уже подтверждён у другого человека.")

    school_class, subject = await ensure_prototype(session)
    if await placed(session, user):
        return PhoneOutcome(True, "known", _known_text(user, school_class.title, subject.title))

    application = await session.get(JoinApplication, user.id)
    if application is not None and application.status == "rejected":
        return PhoneOutcome(
            True,
            "rejected",
            f"Заявку в класс {school_class.title} отклонили. Если это ошибка, напиши учителю.",
        )

    if bootstrap_enabled(settings) and flag.value == "open":
        flag.value = "consumed"
        await _make_teacher(session, user, school_class, subject, application)
        return PhoneOutcome(
            True,
            "teacher",
            f"Ты учитель-администратор. Класс {school_class.title}, предмет {subject.title}.",
        )

    return PhoneOutcome(
        True,
        "choose",
        "Номер подтверждён. Выбери, кто ты, затем школу и класс.",
    )


def _known_text(user: User, class_title: str, subject_title: str) -> str:
    if user.role == "teacher" and user.can_manage_school:
        return f"Ты учитель-администратор. Класс {class_title}, предмет {subject_title}."
    if user.role == "teacher":
        return f"Ты учитель. Класс {class_title}, предмет {subject_title}."
    if user.status == "pending":
        return f"Заявка в класс {class_title} ещё ждёт подтверждения."
    return f"Ты ученик класса {class_title}."


async def _make_teacher(
    session: AsyncSession,
    user: User,
    school_class: SchoolClass,
    subject: Subject,
    application: JoinApplication | None,
) -> None:
    now = datetime.now(UTC)
    user.role = "teacher"
    user.status = "active"
    user.can_manage_school = True
    user.test_signup = True
    link = await session.scalar(
        select(ClassTeacher).where(
            ClassTeacher.class_id == school_class.id,
            ClassTeacher.user_id == user.id,
        )
    )
    if link is None:
        session.add(ClassTeacher(class_id=school_class.id, user_id=user.id))
    post = await session.scalar(
        select(ClassSubjectTeacher).where(
            ClassSubjectTeacher.class_id == school_class.id,
            ClassSubjectTeacher.user_id == user.id,
            ClassSubjectTeacher.subject_id == subject.id,
        )
    )
    if post is None:
        session.add(
            ClassSubjectTeacher(
                class_id=school_class.id,
                user_id=user.id,
                subject_id=subject.id,
            )
        )
    enrollment = await session.scalar(
        select(Enrollment).where(
            Enrollment.class_id == school_class.id,
            Enrollment.user_id == user.id,
        )
    )
    if enrollment is not None:
        await session.delete(enrollment)
    if application is None:
        session.add(
            JoinApplication(
                user_id=user.id,
                wanted_role="teacher",
                school_id=school_class.school_id,
                class_id=school_class.id,
                status="approved",
                created_at=now,
                reviewed_by=user.id,
                reviewed_at=now,
            )
        )
    else:
        application.wanted_role = "teacher"
        application.school_id = school_class.school_id
        application.class_id = school_class.id
        application.status = "approved"
        application.reviewed_by = user.id
        application.reviewed_at = now
    await session.flush()


async def place_in_prototype(
    session: AsyncSession, user: User, role: str
) -> tuple[SchoolClass, Subject]:
    """Роль из первых кнопок бота: сразу в классе 8Б, без школы, города и заявок.
    Прототип — один класс, одобрение не нужно."""
    school_class, subject = await ensure_prototype(session)
    application = await session.get(JoinApplication, user.id)
    if role == "teacher":
        await _make_teacher(session, user, school_class, subject, application)
    else:
        await _make_student_active(session, user, school_class, application)
    return school_class, subject


async def _make_student_active(
    session: AsyncSession,
    user: User,
    school_class: SchoolClass,
    application: JoinApplication | None,
) -> None:
    now = datetime.now(UTC)
    user.role = "student"
    user.status = "active"
    user.can_manage_school = False
    user.test_signup = True
    enrollment = await session.scalar(
        select(Enrollment).where(
            Enrollment.class_id == school_class.id,
            Enrollment.user_id == user.id,
        )
    )
    if enrollment is None:
        session.add(Enrollment(class_id=school_class.id, user_id=user.id, status="active"))
    else:
        enrollment.status = "active"
    if application is None:
        session.add(
            JoinApplication(
                user_id=user.id,
                wanted_role="student",
                school_id=school_class.school_id,
                class_id=school_class.id,
                status="approved",
                created_at=now,
                reviewed_by=user.id,
                reviewed_at=now,
            )
        )
    else:
        application.wanted_role = "student"
        application.school_id = school_class.school_id
        application.class_id = school_class.id
        application.status = "approved"
        application.reviewed_by = user.id
        application.reviewed_at = now
    await session.flush()


async def _make_student(
    session: AsyncSession,
    user: User,
    school_class: SchoolClass,
    application: JoinApplication | None,
) -> None:
    now = datetime.now(UTC)
    user.role = "student"
    user.status = "pending"
    user.can_manage_school = False
    user.test_signup = True
    enrollment = await session.scalar(
        select(Enrollment).where(
            Enrollment.class_id == school_class.id,
            Enrollment.user_id == user.id,
        )
    )
    if enrollment is None:
        session.add(Enrollment(class_id=school_class.id, user_id=user.id, status="pending"))
    else:
        enrollment.status = "pending"
    if application is None:
        session.add(
            JoinApplication(
                user_id=user.id,
                wanted_role="student",
                school_id=school_class.school_id,
                class_id=school_class.id,
                status="pending",
                created_at=now,
            )
        )
    else:
        application.wanted_role = "student"
        application.school_id = school_class.school_id
        application.class_id = school_class.id
        application.status = "pending"
    await session.flush()


async def claims_for(session: AsyncSession, actor: User) -> list[dict]:
    if actor.role != "teacher" or actor.status != "active" or actor.deleted_at is not None:
        return []
    query = (
        select(JoinApplication, User, SchoolClass)
        .join(User, User.id == JoinApplication.user_id)
        .join(SchoolClass, SchoolClass.id == JoinApplication.class_id)
        .where(
            JoinApplication.status == "pending",
            JoinApplication.wanted_role.in_(("student", "teacher")),
        )
        .order_by(JoinApplication.created_at)
    )
    if not actor.can_manage_school:
        class_ids = list(
            await session.scalars(
                select(ClassTeacher.class_id).where(ClassTeacher.user_id == actor.id)
            )
        )
        if not class_ids:
            return []
        query = query.where(JoinApplication.class_id.in_(class_ids))
    rows = (await session.execute(query)).all()
    return [_claim_dict(application, person, school_class) for application, person, school_class in rows]


def _claim_dict(application: JoinApplication, person: User, school_class: SchoolClass) -> dict:
    return {
        "user_id": person.id,
        "display_name": person.display_name,
        "phone_mask": person.phone_mask or "",
        "created_at": application.created_at.isoformat(),
        "class_title": school_class.title,
        "class_id": school_class.id,
        "status": application.status,
        "wanted_role": application.wanted_role,
    }


async def _can_review(session: AsyncSession, actor: User, class_id: int) -> bool:
    if (
        actor.role != "teacher"
        or actor.status != "active"
        or actor.deleted_at is not None
    ):
        return False
    if actor.can_manage_school:
        return True
    link = await session.scalar(
        select(ClassTeacher.user_id).where(
            ClassTeacher.class_id == class_id,
            ClassTeacher.user_id == actor.id,
        )
    )
    return link is not None


async def accept_claim(session: AsyncSession, actor: User, student_id: int) -> tuple[bool, str]:
    if actor.id == student_id or actor.role != "teacher" or actor.status != "active" or actor.deleted_at is not None:
        return False, "Недостаточно прав"
    application = await session.scalar(
        select(JoinApplication)
        .where(JoinApplication.user_id == student_id)
        .with_for_update()
    )
    student = await session.get(User, student_id)
    if (
        application is None
        or student is None
        or application.status != "pending"
        or application.class_id is None
        or application.wanted_role not in {"student", "teacher"}
    ):
        return False, "Заявки нет"
    if not await _can_review(session, actor, application.class_id):
        return False, "Недостаточно прав"
    now = datetime.now(UTC)
    application.status = "approved"
    application.reviewed_by = actor.id
    application.reviewed_at = now
    school_class = await session.get(SchoolClass, application.class_id)
    title = school_class.title if school_class is not None else CLASS_TITLE
    if application.wanted_role == "teacher":
        student.role = "teacher"
        student.status = "active"
        link = await session.scalar(
            select(ClassTeacher).where(
                ClassTeacher.class_id == application.class_id,
                ClassTeacher.user_id == student.id,
            )
        )
        if link is None:
            session.add(ClassTeacher(class_id=application.class_id, user_id=student.id))
        await seed_topics(session)
        subject = await session.scalar(select(Subject).where(Subject.title == SUBJECT_TITLE))
        if subject is not None:
            post = await session.scalar(
                select(ClassSubjectTeacher).where(
                    ClassSubjectTeacher.class_id == application.class_id,
                    ClassSubjectTeacher.user_id == student.id,
                    ClassSubjectTeacher.subject_id == subject.id,
                )
            )
            if post is None:
                session.add(
                    ClassSubjectTeacher(
                        class_id=application.class_id,
                        user_id=student.id,
                        subject_id=subject.id,
                    )
                )
        enrollment = await session.scalar(
            select(Enrollment).where(
                Enrollment.class_id == application.class_id,
                Enrollment.user_id == student.id,
            )
        )
        if enrollment is not None:
            await session.delete(enrollment)
        await enqueue_notice(
            session,
            student.id,
            kind="enrolled",
            title="Тебя приняли в класс",
            body=f"Тебя приняли учителем в класс {title}. Можно открыть кабинет.",
            button_text="Войти в кабинет",
            button_payload="web_login",
        )
        await session.flush()
        return True, student.display_name
    student.role = "student"
    student.status = "active"
    enrollment = await session.scalar(
        select(Enrollment).where(
            Enrollment.class_id == application.class_id,
            Enrollment.user_id == student.id,
        )
    )
    if enrollment is None:
        session.add(Enrollment(class_id=application.class_id, user_id=student.id, status="active"))
    else:
        enrollment.status = "active"
    await enqueue_notice(
        session,
        student.id,
        kind="enrolled",
        title="Тебя приняли в класс",
        body=f"Тебя приняли в класс {title}. Можно открыть кабинет.",
        button_text="Открыть кабинет",
        button_payload="progress",
    )
    await session.flush()
    return True, student.display_name


async def reject_claim(session: AsyncSession, actor: User, student_id: int) -> tuple[bool, str]:
    if actor.id == student_id or actor.role != "teacher" or actor.status != "active" or actor.deleted_at is not None:
        return False, "Недостаточно прав"
    application = await session.scalar(
        select(JoinApplication)
        .where(JoinApplication.user_id == student_id)
        .with_for_update()
    )
    student = await session.get(User, student_id)
    if application is None or student is None or application.status != "pending" or application.class_id is None:
        return False, "Заявки нет"
    if not await _can_review(session, actor, application.class_id):
        return False, "Недостаточно прав"
    now = datetime.now(UTC)
    application.status = "rejected"
    application.reviewed_by = actor.id
    application.reviewed_at = now
    student.status = "pending"
    if application.class_id is not None:
        enrollment = await session.scalar(
            select(Enrollment).where(
                Enrollment.class_id == application.class_id,
                Enrollment.user_id == student.id,
                Enrollment.status == "pending",
            )
        )
        if enrollment is not None:
            await session.delete(enrollment)
    school_class = (
        await session.get(SchoolClass, application.class_id) if application.class_id else None
    )
    title = school_class.title if school_class is not None else CLASS_TITLE
    await enqueue_notice(
        session,
        student.id,
        kind="rejected",
        title="Заявку отклонили",
        body=f"Заявку в класс {title} отклонили. Если это ошибка, напиши учителю.",
        button_text="",
        button_payload="",
    )
    await session.flush()
    return True, student.display_name


async def enqueue_notice(
    session: AsyncSession,
    user_id: int,
    *,
    kind: str,
    title: str,
    body: str,
    button_text: str,
    button_payload: str,
    ref_id: int | None = None,
) -> None:
    now = datetime.now(UTC)
    session.add(
        Notice(
            user_id=user_id,
            kind=kind[:32],
            title=title[:200],
            body=body[:500],
            ref_id=ref_id,
            created_at=now,
        )
    )
    identity = await session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.user_id == user_id,
            AuthIdentity.provider == "max",
            AuthIdentity.revoked_at.is_(None),
        )
    )
    session.add(
        OutboundNotice(
            user_id=user_id,
            kind=kind[:32],
            title=title[:200],
            body=body[:500],
            button_text=button_text[:128],
            button_payload=button_payload[:128],
            ref_id=ref_id,
            status="pending" if identity is not None else "failed",
            attempts=0,
            last_error=None if identity is not None else "no_max",
            created_at=now,
        )
    )


async def active_managers(session: AsyncSession) -> list[User]:
    return list(
        await session.scalars(
            select(User)
            .where(
                User.can_manage_school.is_(True),
                User.role == "teacher",
                User.status == "active",
                User.deleted_at.is_(None),
            )
            .order_by(User.id)
        )
    )


async def notify_new_claim(
    session: AsyncSession,
    student: User,
    school_class: SchoolClass,
    settings: Settings,
) -> bool:
    """Сообщить ответственному. Если его нет, это пишется в аудит, а не теряется."""
    managers = await active_managers(session)
    if not managers:
        now = datetime.now(UTC)
        session.add(
            AuditLog(
                actor_user_id=None,
                action="claims_without_manager",
                target_user_id=student.id,
                ip=None,
                detail=f"class {school_class.title}"[:300],
                created_at=now,
            )
        )
        await _tell_operators(session, student, school_class, settings)
        return False
    for manager in managers:
        await enqueue_notice(
            session,
            manager.id,
            kind="join_request",
            title=f"Новая заявка в класс {school_class.title}",
            body=(
                f"Новая заявка в класс {school_class.title}.\n"
                f"{student.display_name}.\n"
                "Ждёт решения."
            ),
            button_text="",
            button_payload="",
            ref_id=student.id,
        )
    return True


async def _tell_operators(
    session: AsyncSession,
    student: User,
    school_class: SchoolClass,
    settings: Settings,
) -> None:
    raw = {item.strip() for item in settings.admin_max_ids.split(",") if item.strip()}
    if not raw:
        return
    rows = await session.execute(
        select(User)
        .join(AuthIdentity, AuthIdentity.user_id == User.id)
        .where(
            AuthIdentity.provider == "max",
            AuthIdentity.external_id.in_(raw),
            AuthIdentity.revoked_at.is_(None),
            User.deleted_at.is_(None),
        )
    )
    for operator in rows.scalars():
        await enqueue_notice(
            session,
            operator.id,
            kind="claims_gap",
            title="Заявку некому принять",
            body=(
                f"В классе {school_class.title} новая заявка от {student.display_name}. "
                "Учителя-администратора нет. Назначь его командой grant-school-manager."
            ),
            button_text="",
            button_payload="",
            ref_id=student.id,
        )


async def reviewer_name(session: AsyncSession) -> str | None:
    found = await session.scalar(
        select(User.display_name)
        .where(
            User.can_manage_school.is_(True),
            User.deleted_at.is_(None),
            User.status == "active",
            User.role == "teacher",
        )
        .order_by(User.id)
    )
    return found
