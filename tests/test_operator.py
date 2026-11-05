from sqlalchemy import select

from app.db.models import ClassTeacher, Enrollment, User
from app.domain.accounts import accept_consent
from app.domain.operator import people_text, place_student, place_teacher
from app.domain.school_admin import grant_school_manager


async def test_desk_places_student_and_keeps_the_only_manager(api):
    factory = api.app.state.session_factory
    async with factory() as session:
        manager = await accept_consent(session, "930001", "Марина", api.settings)
        pupil = await accept_consent(session, "930002", "Егор", api.settings)
        await session.commit()
        manager_id = manager.id
        pupil_id = pupil.id
    async with factory() as session:
        granted = await grant_school_manager(session, "930001", apply=True)
        await session.commit()
    assert granted.changed
    async with factory() as session:
        school_class_id = (
            await session.scalars(select(ClassTeacher.class_id).where(ClassTeacher.user_id == manager_id))
        ).one()
        refused = await place_student(session, manager_id, school_class_id)
        await session.commit()
    assert refused.changed is False
    async with factory() as session:
        step = await place_student(session, pupil_id, school_class_id)
        listed = await people_text(session)
        await session.commit()
        stored = await session.get(User, pupil_id)
        seat = await session.scalar(
            select(Enrollment).where(
                Enrollment.user_id == pupil_id,
                Enrollment.class_id == school_class_id,
                Enrollment.status == "active",
            )
        )
    assert step.changed
    assert stored.role == "student"
    assert stored.can_manage_school is False
    assert seat is not None
    assert "Егор" in listed
    assert "phone" not in listed

    async with factory() as session:
        taught = await place_teacher(session, pupil_id, school_class_id)
        await session.commit()
        teacher = await session.get(User, pupil_id)
        link = await session.scalar(
            select(ClassTeacher).where(
                ClassTeacher.user_id == pupil_id,
                ClassTeacher.class_id == school_class_id,
            )
        )
        gone = await session.scalar(select(Enrollment).where(Enrollment.user_id == pupil_id))
    assert taught.changed
    assert teacher.role == "teacher"
    assert teacher.can_manage_school is False
    assert link is not None
    assert gone is None
