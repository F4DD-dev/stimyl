import asyncio

from sqlalchemy import func, select

from app.db.models import AuditLog, Enrollment, JoinApplication, OutboundNotice, RuntimeFlag, User
from app.domain.accounts import accept_consent
from app.domain.directory import file_student_application
from app.domain.onboarding import (
    BOOTSTRAP_KEY,
    accept_claim,
    ensure_prototype,
    register_phone,
    reject_claim,
)
from app.domain.school_admin import grant_school_manager, transfer_school_manager
from tests.support import message, post_update
from tests.test_onboarding import _consent, _contact, _started


async def _claim(api, user_id: int) -> None:
    factory = api.app.state.session_factory
    async with factory() as session:
        user = await session.get(User, user_id)
        school_class, _subject = await ensure_prototype(session)
        await file_student_application(session, user, school_class, api.settings)
        await session.commit()


async def _person(api, external_id: str, name: str, digits: str) -> int:
    factory = api.app.state.session_factory
    async with factory() as session:
        user = await accept_consent(session, external_id, name, api.settings)
        await session.commit()
        user_id = user.id
    async with factory() as session:
        user = await session.get(User, user_id)
        await register_phone(session, user, digits, api.settings)
        await session.commit()
    return user_id


async def test_plain_teacher_student_and_technical_admin_cannot_accept(api):
    api.settings.env = "prod"
    api.settings.first_teacher_bootstrap = True
    api.settings.admin_max_ids = "910001"
    factory = api.app.state.session_factory
    async with factory() as session:
        operator = await accept_consent(session, "910001", "Оператор", api.settings)
        await session.commit()
        operator_id = operator.id
    assert operator.role == "admin"
    assert operator.can_manage_school is False
    student_id = await _person(api, "910002", "Егор", "79004440002")
    async with factory() as session:
        operator = await session.get(User, operator_id)
        student = await session.get(User, student_id)
        student.role = "teacher"
        student.can_manage_school = False
        await session.commit()
        denied_teacher = await accept_claim(session, student, student_id)
        pupil = await session.get(User, student_id)
        pupil.role = "student"
        await session.commit()
        denied_student = await accept_claim(session, pupil, operator_id)
        denied_admin = await accept_claim(session, operator, student_id)
    assert denied_teacher == (False, "Недостаточно прав")
    assert denied_student == (False, "Недостаточно прав")
    assert denied_admin == (False, "Недостаточно прав")
    async with factory() as session:
        stored = await session.get(User, operator_id)
    assert stored.can_manage_school is False


async def test_manager_can_accept_once_and_a_second_click_does_not_duplicate(api):
    api.settings.first_teacher_bootstrap = True
    teacher_id = await _person(api, "920001", "Марина", "79005550001")
    student_id = await _person(api, "920002", "Егор", "79005550002")
    await _claim(api, student_id)
    factory = api.app.state.session_factory

    async def once() -> bool:
        async with factory() as session:
            actor = await session.get(User, teacher_id)
            ok, _detail = await accept_claim(session, actor, student_id)
            await session.commit()
            return ok

    results = await asyncio.gather(once(), once())
    assert sorted(results) == [False, True]
    async with factory() as session:
        seats = list(
            await session.scalars(
                select(Enrollment).where(Enrollment.user_id == student_id, Enrollment.status == "active")
            )
        )
        application = await session.get(JoinApplication, student_id)
        notices = list(
            await session.scalars(
                select(OutboundNotice).where(
                    OutboundNotice.user_id == student_id,
                    OutboundNotice.kind == "enrolled",
                )
            )
        )
    assert len(seats) == 1
    assert application.status == "approved"
    assert application.reviewed_by == teacher_id
    assert len(notices) == 1


async def test_missing_manager_is_explicit_and_grant_reopens_the_queue(api):
    api.settings.env = "prod"
    api.settings.first_teacher_bootstrap = False
    student_id = await _person(api, "930002", "Егор", "79006660002")
    await _claim(api, student_id)
    factory = api.app.state.session_factory
    async with factory() as session:
        flag = await session.get(RuntimeFlag, BOOTSTRAP_KEY)
        gap = await session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "claims_without_manager")
        )
        sent = await session.scalar(
            select(func.count())
            .select_from(OutboundNotice)
            .where(OutboundNotice.kind == "join_request", OutboundNotice.ref_id == student_id)
        )
    assert flag.value == "open"
    assert int(gap or 0) == 1
    assert int(sent or 0) == 0

    async with factory() as session:
        preview = await grant_school_manager(session, "Егор", apply=False)
        await session.commit()
    assert preview.ok is False
    assert preview.changed is False

    async with factory() as session:
        dry = await grant_school_manager(session, "930001", apply=False)
        await session.rollback()
    assert dry.changed is False

    await _person(api, "930001", "Лев", "79006660001")
    async with factory() as session:
        preview = await grant_school_manager(session, "930001", apply=False)
        await session.rollback()
        stored = await session.get(User, await _id(factory, "930001"))
    assert preview.ok is True
    assert "Изменений нет" in preview.text
    assert stored.can_manage_school is False

    async with factory() as session:
        done = await grant_school_manager(session, "930001", apply=True)
        await session.commit()
    assert done.changed is True
    async with factory() as session:
        manager = await _user_by_max(session, "930001")
        flag = await session.get(RuntimeFlag, BOOTSTRAP_KEY)
        queue = list(
            await session.scalars(
                select(OutboundNotice).where(OutboundNotice.user_id == manager.id, OutboundNotice.kind == "join_queue")
            )
        )
    assert manager.role == "teacher"
    assert manager.can_manage_school is True
    assert flag.value == "consumed"
    assert queue and "заявки" in queue[0].body.casefold()

    api.settings.first_teacher_bootstrap = True
    api.settings.env = "dev"
    later_id = await _person(api, "930003", "Оля", "79006660003")
    async with factory() as session:
        later = await session.get(User, later_id)
        bosses = await session.scalar(
            select(func.count()).select_from(User).where(User.can_manage_school.is_(True))
        )
    assert later.role == "student"
    assert int(bosses or 0) == 1

    async with factory() as session:
        actor = await session.get(User, manager.id)
        ok, name = await accept_claim(session, actor, student_id)
        await session.commit()
    assert ok is True
    assert name == "Егор"


async def test_new_claim_notifies_the_manager_with_three_buttons(api):
    api.settings.first_teacher_bootstrap = True
    api.settings.bot_username = "ideya_fiks_101_bot"
    api.settings.bot_contact_id = 387830563
    token = api.settings.max_token or ""
    await post_update(api, _started(940001, "Марина"))
    await post_update(api, _consent(940001, "Марина"))
    await post_update(api, _contact(940001, "Марина", "marina-phone", "79007770001", token))
    await post_update(api, _started(940002, "Егор"))
    await post_update(api, _consent(940002, "Егор"))
    await post_update(api, _contact(940002, "Егор", "egor-phone", "79007770002", token))
    assert "кто ты" in api.memory.sent[-1]["text"].casefold()
    from tests.test_onboarding import _click

    await _click(api, 940002, "Егор", "role:student")
    await _click(api, 940002, "Егор", "city:0")
    await _click(api, 940002, "Егор", "school:blg-16")
    await _click(api, 940002, "Егор", "8Б", by_text=True)
    assert "заявк" in api.memory.sent[-1]["text"].casefold()

    from app.bot.delivery import send_pending_notices

    factory = api.app.state.session_factory
    async with factory() as session:
        await send_pending_notices(session, api.memory)
        await session.commit()
    found = [item for item in api.memory.sent if "Новая заявка в класс 8Б" in item["text"]]
    assert found
    labels = {button["text"] for button in found[-1]["buttons"]}
    assert labels == {"Принять", "Отклонить", "Заявки"}

    await post_update(api, message(940002, "Егор", "заявки", "egor-apps"))
    assert "подожд" in api.memory.sent[-1]["text"].casefold()


async def test_transfer_moves_the_flag_and_preview_does_not(api):
    api.settings.first_teacher_bootstrap = True
    await _person(api, "950001", "Марина", "79008880001")
    await _person(api, "950002", "Лев", "79008880002")
    factory = api.app.state.session_factory
    async with factory() as session:
        preview = await transfer_school_manager(session, "950001", "950002", apply=False)
        await session.rollback()
        source = await _user_by_max(session, "950001")
    assert "Изменений нет" in preview.text
    assert source.can_manage_school is True
    async with factory() as session:
        done = await transfer_school_manager(session, "950001", "950002", apply=True)
        await session.commit()
        source = await _user_by_max(session, "950001")
        target = await _user_by_max(session, "950002")
        refused, _detail = await reject_claim(session, source, target.id)
    assert done.changed is True
    assert source.role == "teacher"
    assert source.can_manage_school is False
    assert target.can_manage_school is True
    assert refused is False


async def _id(factory, external_id: str) -> int:
    async with factory() as session:
        user = await _user_by_max(session, external_id)
        return user.id


async def _user_by_max(session, external_id: str) -> User:
    from app.db.models import AuthIdentity

    identity = await session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == "max",
            AuthIdentity.external_id == external_id,
        )
    )
    user = await session.get(User, identity.user_id)
    assert user is not None
    return user
