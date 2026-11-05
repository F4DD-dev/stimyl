"""Правки людей и классов из локальной консоли. Переписку не читает."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuthIdentity,
    ClassSubjectTeacher,
    ClassTeacher,
    Enrollment,
    JoinApplication,
    School,
    SchoolClass,
    Subject,
    User,
)
from app.domain.accounts import approve_teacher, write_audit
from app.domain.onboarding import active_managers


@dataclass(frozen=True)
class Step:
    changed: bool
    text: str


async def people_text(session: AsyncSession) -> str:
    rows = (
        await session.execute(
            select(User, AuthIdentity.external_id)
            .outerjoin(
                AuthIdentity,
                (AuthIdentity.user_id == User.id)
                & (AuthIdentity.provider == "max")
                & (AuthIdentity.revoked_at.is_(None)),
            )
            .order_by(User.id)
        )
    ).all()
    if not rows:
        return "Людей нет. Консоль никого не создаёт: сначала «Согласен» в боте."
    lines = ["id\tроль\tстатус\tуправление\tmax\tимя\tгде"]
    for user, external_id in rows:
        closed = " скрыт" if user.deleted_at is not None else ""
        manage = "да" if user.can_manage_school else "нет"
        lines.append(
            f"{user.id}\t{user.role}\t{user.status}{closed}\t{manage}\t"
            f"{external_id or '-'}\t{user.display_name}\t{await _where(session, user.id)}"
        )
    return "\n".join(lines)


async def schools_text(session: AsyncSession) -> str:
    schools = list(await session.scalars(select(School).order_by(School.id)))
    classes = list(await session.scalars(select(SchoolClass).order_by(SchoolClass.id)))
    subjects = list(await session.scalars(select(Subject).order_by(Subject.id)))
    if not schools and not subjects:
        return "Школ и предметов нет."
    lines: list[str] = []
    for school in schools:
        lines.append(f"школа {school.id}\t{school.title}")
        for item in classes:
            if item.school_id == school.id:
                lines.append(
                    f"  класс {item.id}\t{item.title}\tкод {item.join_code}\tключ {item.join_key}"
                )
    if subjects:
        lines.append("предметы")
        for subject in subjects:
            lines.append(f"  предмет {subject.id}\t{subject.title}")
    return "\n".join(lines)


async def place_student(session: AsyncSession, user_id: int, class_id: int | None) -> Step:
    user = await _open_user(session, user_id)
    if isinstance(user, Step):
        return user
    if await _only_manager(session, user):
        return Step(False, "Это единственный ответственный. Сначала передай управление.")
    school_class = await _class_or_stop(session, class_id)
    if isinstance(school_class, Step):
        return school_class
    user.role = "student"
    user.status = "active"
    user.can_manage_school = False
    await session.execute(delete(ClassTeacher).where(ClassTeacher.user_id == user.id))
    await session.execute(delete(ClassSubjectTeacher).where(ClassSubjectTeacher.user_id == user.id))
    if school_class is not None:
        await _seat_student(session, user, school_class)
    await write_audit(session, None, "desk_student", user.id, None, _class_detail(school_class))
    where = school_class.title if school_class is not None else "без класса"
    return Step(True, f"{user.display_name} теперь ученик, {where}.")


async def place_teacher(session: AsyncSession, user_id: int, class_id: int | None) -> Step:
    user = await _open_user(session, user_id)
    if isinstance(user, Step):
        return user
    school_class = await _class_or_stop(session, class_id)
    if isinstance(school_class, Step):
        return school_class
    kept_manage = user.can_manage_school and await _only_manager(session, user)
    if not await approve_teacher(session, user.id, None):
        return Step(False, "Человек не найден.")
    if user.can_manage_school and not kept_manage:
        user.can_manage_school = False
    if school_class is not None:
        await _link_class(session, user.id, school_class.id)
    await write_audit(session, None, "desk_teacher", user.id, None, _class_detail(school_class))
    manage = "управление остаётся" if user.can_manage_school else "без управления"
    where = school_class.title if school_class is not None else "без класса"
    return Step(True, f"{user.display_name} теперь учитель, {where}, {manage}.")


async def link_subject(
    session: AsyncSession, user_id: int, class_id: int, subject_id: int
) -> Step:
    user = await _open_user(session, user_id)
    if isinstance(user, Step):
        return user
    if user.role != "teacher":
        return Step(False, "Предмет ведёт учитель. Сначала смени роль.")
    school_class = await session.get(SchoolClass, class_id)
    subject = await session.get(Subject, subject_id)
    if school_class is None or subject is None:
        return Step(False, "Класс или предмет не найден.")
    await _link_class(session, user.id, school_class.id)
    found = await session.scalar(
        select(ClassSubjectTeacher).where(
            ClassSubjectTeacher.class_id == school_class.id,
            ClassSubjectTeacher.user_id == user.id,
            ClassSubjectTeacher.subject_id == subject.id,
        )
    )
    if found is None:
        session.add(
            ClassSubjectTeacher(
                class_id=school_class.id,
                user_id=user.id,
                subject_id=subject.id,
            )
        )
    await write_audit(
        session,
        None,
        "desk_subject",
        user.id,
        None,
        f"class {school_class.id} subject {subject.id}",
    )
    return Step(True, f"{user.display_name} ведёт {subject.title} в классе {school_class.title}.")


async def _where(session: AsyncSession, user_id: int) -> str:
    seated = list(
        await session.scalars(
            select(SchoolClass.title)
            .join(Enrollment, Enrollment.class_id == SchoolClass.id)
            .where(Enrollment.user_id == user_id, Enrollment.status == "active")
            .order_by(SchoolClass.title)
        )
    )
    taught = list(
        await session.scalars(
            select(SchoolClass.title)
            .join(ClassTeacher, ClassTeacher.class_id == SchoolClass.id)
            .where(ClassTeacher.user_id == user_id)
            .order_by(SchoolClass.title)
        )
    )
    parts: list[str] = []
    if seated:
        parts.append("ученик " + ", ".join(seated))
    if taught:
        parts.append("учитель " + ", ".join(taught))
    return "; ".join(parts) if parts else "без класса"


async def id_hint(session: AsyncSession, user_id: int) -> str | None:
    """Если ввели колонку max, сказать внутренний id. None значит id уже внутренний."""
    if await session.get(User, user_id) is not None:
        return None
    identity = await session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "max",
            AuthIdentity.external_id == str(user_id),
            AuthIdentity.revoked_at.is_(None),
        )
    )
    if identity is None:
        return "Человек с таким внутренним id не найден. Нужна первая колонка id, не max."
    owner = await session.get(User, identity.user_id)
    name = owner.display_name if owner is not None else "этого человека"
    return f"{user_id} — это колонка max. У {name} внутренний id {identity.user_id}."


async def _open_user(session: AsyncSession, user_id: int) -> User | Step:
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return Step(False, "Человек не найден или скрыт.")
    return user


async def _class_or_stop(session: AsyncSession, class_id: int | None) -> SchoolClass | None | Step:
    if class_id is None:
        return None
    school_class = await session.get(SchoolClass, class_id)
    if school_class is None:
        return Step(False, "Класс не найден.")
    return school_class


async def _only_manager(session: AsyncSession, user: User) -> bool:
    if not user.can_manage_school:
        return False
    managers = await active_managers(session)
    return len(managers) <= 1


async def _seat_student(session: AsyncSession, user: User, school_class: SchoolClass) -> None:
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
    application = await session.get(JoinApplication, user.id)
    if application is None:
        session.add(
            JoinApplication(
                user_id=user.id,
                wanted_role="student",
                school_id=school_class.school_id,
                class_id=school_class.id,
                status="approved",
                created_at=datetime.now(UTC),
            )
        )
    else:
        application.wanted_role = "student"
        application.school_id = school_class.school_id
        application.class_id = school_class.id
        application.status = "approved"


async def _link_class(session: AsyncSession, user_id: int, class_id: int) -> None:
    link = await session.scalar(
        select(ClassTeacher).where(
            ClassTeacher.class_id == class_id,
            ClassTeacher.user_id == user_id,
        )
    )
    if link is None:
        session.add(ClassTeacher(class_id=class_id, user_id=user_id))
    await session.execute(
        delete(Enrollment).where(Enrollment.class_id == class_id, Enrollment.user_id == user_id)
    )


def _class_detail(school_class: SchoolClass | None) -> str | None:
    if school_class is None:
        return None
    return f"class {school_class.id}"
