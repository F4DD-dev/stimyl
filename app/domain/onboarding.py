"""Первый учитель и заявки учеников. Победителя определяет строка-флаг, не число пользователей."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
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


async def ensure_prototype(session: AsyncSession) -> tuple[SchoolClass, Subject]:
    """Класс 8Б и математика. Повтор ничего не дублирует и людей не создаёт."""
    await seed_topics(session)
    subject = await session.scalar(select(Subject).where(Subject.title == SUBJECT_TITLE))
    if subject is None:
        raise RuntimeError("subject missing")
    school_class = await session.scalar(
        select(SchoolClass).where(SchoolClass.title == CLASS_TITLE).order_by(SchoolClass.id)
    )
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

    await _make_student(session, user, school_class, application)
    return PhoneOutcome(
        True,
        "student",
        f"Заявка в класс {school_class.title} отправлена учителю и ждёт подтверждения.",
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
    if not actor.can_manage_school:
        return []
    rows = (
        await session.execute(
            select(JoinApplication, User, SchoolClass)
            .join(User, User.id == JoinApplication.user_id)
            .join(SchoolClass, SchoolClass.id == JoinApplication.class_id)
            .where(JoinApplication.status == "pending", JoinApplication.wanted_role == "student")
            .order_by(JoinApplication.created_at)
        )
    ).all()
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
    }


async def accept_claim(session: AsyncSession, actor: User, student_id: int) -> tuple[bool, str]:
    if not actor.can_manage_school or actor.id == student_id:
        return False, "Недостаточно прав"
    application = await session.get(JoinApplication, student_id)
    student = await session.get(User, student_id)
    if (
        application is None
        or student is None
        or application.status != "pending"
        or application.class_id is None
        or application.wanted_role != "student"
    ):
        return False, "Заявки нет"
    now = datetime.now(UTC)
    application.status = "approved"
    application.reviewed_by = actor.id
    application.reviewed_at = now
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
    school_class = await session.get(SchoolClass, application.class_id)
    title = school_class.title if school_class is not None else CLASS_TITLE
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
    if not actor.can_manage_school or actor.id == student_id:
        return False, "Недостаточно прав"
    application = await session.get(JoinApplication, student_id)
    student = await session.get(User, student_id)
    if application is None or student is None or application.status != "pending":
        return False, "Заявки нет"
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
