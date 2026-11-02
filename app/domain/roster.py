"""Список людей тестового проекта. Телефон наружу уходит только маской."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ClassSubjectTeacher,
    ClassTeacher,
    Enrollment,
    SchoolClass,
    Subject,
    User,
)


async def list_people(
    session: AsyncSession,
    *,
    query: str,
    role: str,
    status: str,
) -> list[dict]:
    statement = select(User).where(User.deleted_at.is_(None)).order_by(User.id)
    if role in {"student", "teacher"}:
        statement = statement.where(User.role == role)
    if status in {"pending", "active", "blocked"}:
        statement = statement.where(User.status == status)
    cleaned = query.strip()
    if cleaned:
        statement = statement.where(User.display_name.ilike(f"%{cleaned[:80]}%"))
    people = list(await session.scalars(statement.limit(200)))
    return [await _person(session, person) for person in people]


async def person_detail(session: AsyncSession, user_id: int) -> dict | None:
    person = await session.get(User, user_id)
    if person is None or person.deleted_at is not None:
        return None
    return await _person(session, person)


async def update_person(
    session: AsyncSession,
    actor: User,
    user_id: int,
    *,
    role: str | None,
    status: str | None,
    can_manage_school: bool | None,
    display_name: str | None,
) -> tuple[dict | None, str | None, int]:
    person = await session.get(User, user_id)
    if person is None or person.deleted_at is not None:
        return None, "Человека нет", 404
    if role is not None and role not in {"student", "teacher"}:
        return None, "Роль может быть учеником или учителем", 422
    if status is not None and status not in {"pending", "active", "blocked"}:
        return None, "Некорректный статус", 422
    if person.id == actor.id and status == "blocked":
        return None, "Себя заблокировать нельзя", 409
    next_manage = person.can_manage_school if can_manage_school is None else can_manage_school
    next_role = role or person.role
    if next_manage and next_role != "teacher":
        return None, "Управлять школой может только учитель", 422
    if person.can_manage_school and not next_manage:
        others = await session.scalar(
            select(User.id).where(
                User.can_manage_school.is_(True),
                User.id != person.id,
                User.deleted_at.is_(None),
                User.status == "active",
            )
        )
        if others is None:
            return None, "Нужен хотя бы один учитель-администратор", 409
    if role is not None:
        person.role = role
    if status is not None:
        person.status = status
    if can_manage_school is not None:
        person.can_manage_school = can_manage_school
    if display_name is not None and display_name.strip():
        person.display_name = display_name.strip()[:200]
    await session.flush()
    return await _person(session, person), None, 200


async def appoint(
    session: AsyncSession,
    *,
    user_id: int,
    class_id: int,
    subject_id: int,
) -> tuple[bool, str]:
    person = await session.get(User, user_id)
    school_class = await session.get(SchoolClass, class_id)
    subject = await session.get(Subject, subject_id)
    if person is None or person.deleted_at is not None or person.role != "teacher" or person.status != "active":
        return False, "Назначить можно действующего учителя"
    if school_class is None or subject is None:
        return False, "Класс или предмет не найден"
    link = await session.scalar(
        select(ClassTeacher).where(
            ClassTeacher.class_id == class_id,
            ClassTeacher.user_id == user_id,
        )
    )
    if link is None:
        session.add(ClassTeacher(class_id=class_id, user_id=user_id))
    post = await session.scalar(
        select(ClassSubjectTeacher).where(
            ClassSubjectTeacher.class_id == class_id,
            ClassSubjectTeacher.user_id == user_id,
            ClassSubjectTeacher.subject_id == subject_id,
        )
    )
    if post is None:
        session.add(
            ClassSubjectTeacher(class_id=class_id, user_id=user_id, subject_id=subject_id)
        )
    await session.flush()
    return True, person.display_name


async def withdraw(
    session: AsyncSession,
    *,
    user_id: int,
    class_id: int,
    subject_id: int,
) -> bool:
    post = await session.scalar(
        select(ClassSubjectTeacher).where(
            ClassSubjectTeacher.class_id == class_id,
            ClassSubjectTeacher.user_id == user_id,
            ClassSubjectTeacher.subject_id == subject_id,
        )
    )
    if post is None:
        return False
    await session.delete(post)
    left = await session.scalar(
        select(ClassSubjectTeacher.subject_id).where(
            ClassSubjectTeacher.class_id == class_id,
            ClassSubjectTeacher.user_id == user_id,
        )
    )
    if left is None:
        link = await session.scalar(
            select(ClassTeacher).where(
                ClassTeacher.class_id == class_id,
                ClassTeacher.user_id == user_id,
            )
        )
        if link is not None:
            await session.delete(link)
    await session.flush()
    return True


async def catalog(session: AsyncSession) -> dict:
    classes = list(await session.scalars(select(SchoolClass).order_by(SchoolClass.id)))
    subjects = list(await session.scalars(select(Subject).order_by(Subject.id)))
    return {
        "classes": [{"id": row.id, "title": row.title} for row in classes],
        "subjects": [{"id": row.id, "title": row.title} for row in subjects],
    }


async def _person(session: AsyncSession, person: User) -> dict:
    classes = (
        await session.execute(
            select(SchoolClass.title)
            .join(Enrollment, Enrollment.class_id == SchoolClass.id)
            .where(Enrollment.user_id == person.id, Enrollment.status == "active")
            .order_by(SchoolClass.id)
        )
    ).all()
    if not classes:
        classes = (
            await session.execute(
                select(SchoolClass.title)
                .join(ClassTeacher, ClassTeacher.class_id == SchoolClass.id)
                .where(ClassTeacher.user_id == person.id)
                .order_by(SchoolClass.id)
            )
        ).all()
    subjects = (
        await session.execute(
            select(Subject.title)
            .join(ClassSubjectTeacher, ClassSubjectTeacher.subject_id == Subject.id)
            .where(ClassSubjectTeacher.user_id == person.id)
            .order_by(Subject.title)
        )
    ).all()
    return {
        "id": person.id,
        "display_name": person.display_name,
        "role": person.role,
        "status": person.status,
        "can_manage_school": person.can_manage_school,
        "phone_mask": person.phone_mask or "",
        "test_signup": person.test_signup,
        "created_at": person.created_at.isoformat() if person.created_at else "",
        "classes": [row.title for row in classes],
        "subjects": [row.title for row in subjects],
    }
