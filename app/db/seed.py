import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import ClassTeacher, Enrollment, SchoolClass, Subject, Topic, User
from app.db.session import make_engine, make_session_factory
from app.domain.curriculum import DEMO_CLASS_TITLE, DEMO_SUBJECT_TITLE, TOPICS

DEMO_TEACHER = ("900001", "Марина Сергеевна")
DEMO_STUDENTS = (
    ("900002", "Алексей"),
    ("900003", "Аня"),
    ("900004", "Кирилл"),
    ("900005", "Ольга"),
)


async def seed(session: AsyncSession, teacher_max_user_id: str | None = None) -> None:
    school = await _class(session)
    subject = await _subject(session)
    await _topics(session, subject)
    teacher_ids = {DEMO_TEACHER[0]}
    if teacher_max_user_id:
        teacher_ids.add(teacher_max_user_id)
    await _ensure_user(session, DEMO_TEACHER[0], DEMO_TEACHER[1], "teacher")
    if teacher_max_user_id and teacher_max_user_id != DEMO_TEACHER[0]:
        await _ensure_user(session, teacher_max_user_id, "Учитель", "teacher")
    for max_id, name in ((DEMO_TEACHER[0], DEMO_TEACHER[1]),):
        await _link_teacher(session, school, max_id)
    if teacher_max_user_id:
        await _link_teacher(session, school, teacher_max_user_id)
    for max_id, name in DEMO_STUDENTS:
        if max_id in teacher_ids:
            continue
        await _ensure_user(session, max_id, name, "student")
        await _enroll(session, school, max_id)


async def _class(session: AsyncSession) -> SchoolClass:
    found = await session.scalar(select(SchoolClass).where(SchoolClass.title == DEMO_CLASS_TITLE))
    if found is not None:
        return found
    found = SchoolClass(title=DEMO_CLASS_TITLE)
    session.add(found)
    await session.flush()
    return found


async def _subject(session: AsyncSession) -> Subject:
    found = await session.scalar(select(Subject).where(Subject.title == DEMO_SUBJECT_TITLE))
    if found is not None:
        return found
    found = Subject(title=DEMO_SUBJECT_TITLE)
    session.add(found)
    await session.flush()
    return found


async def _topics(session: AsyncSession, subject: Subject) -> None:
    for position, material in enumerate(TOPICS, start=1):
        found = await session.scalar(
            select(Topic).where(Topic.subject_id == subject.id, Topic.title == material.title)
        )
        if found is None:
            session.add(Topic(subject_id=subject.id, title=material.title, position=position))
        elif found.position != position:
            found.position = position
    await session.flush()


async def _ensure_user(session: AsyncSession, max_id: str, name: str, role: str) -> User:
    found = await session.scalar(select(User).where(User.max_user_id == max_id))
    if found is None:
        found = User(max_user_id=max_id, display_name=name, role=role)
        session.add(found)
        await session.flush()
        return found
    if role == "teacher" and found.role != "teacher":
        found.role = "teacher"
        await session.flush()
    return found


async def _link_teacher(session: AsyncSession, school: SchoolClass, max_id: str) -> None:
    user = await session.scalar(select(User).where(User.max_user_id == max_id))
    if user is None:
        return
    link = await session.scalar(
        select(ClassTeacher).where(
            ClassTeacher.class_id == school.id,
            ClassTeacher.user_id == user.id,
        )
    )
    if link is None:
        session.add(ClassTeacher(class_id=school.id, user_id=user.id))
    enrollment = await session.scalar(
        select(Enrollment).where(Enrollment.class_id == school.id, Enrollment.user_id == user.id)
    )
    if enrollment is not None:
        await session.delete(enrollment)
    await session.flush()


async def _enroll(session: AsyncSession, school: SchoolClass, max_id: str) -> None:
    user = await session.scalar(select(User).where(User.max_user_id == max_id))
    if user is None or user.role != "student":
        return
    found = await session.scalar(
        select(Enrollment).where(Enrollment.class_id == school.id, Enrollment.user_id == user.id)
    )
    if found is None:
        session.add(Enrollment(class_id=school.id, user_id=user.id))
        await session.flush()


def main() -> None:
    asyncio.run(_run())


async def _run() -> None:
    settings = get_settings()
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    async with factory() as session:
        await seed(session, settings.teacher_max_user_id)
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    main()
