import re
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db.models import (
    Attempt,
    AuthIdentity,
    LearningSession,
    SchoolClass,
    TeacherApplication,
    User,
)
from app.domain.accounts import (
    BOT_PROVIDER,
    WEBAPP_PROVIDER,
    accept_consent,
    add_class,
    add_school,
    approve_teacher,
    create_transfer,
    delete_user_data,
    set_blocked,
)
from tests.support import auth_as, message, post_update, sign_init_data


def _started(user_id: int, name: str, payload: str | None = None) -> dict:
    body = {
        "update_type": "bot_started",
        "timestamp": user_id,
        "chat_id": 8000 + user_id,
        "user": {"user_id": user_id, "first_name": name, "is_bot": False},
    }
    if payload:
        body["payload"] = payload
    return body


def _consent(user_id: int, name: str) -> dict:
    return {
        "update_type": "message_callback",
        "timestamp": user_id + 1,
        "callback": {
            "timestamp": user_id + 1,
            "callback_id": f"consent-{user_id}",
            "payload": "consent_yes",
            "user": {"user_id": user_id, "first_name": name, "is_bot": False},
        },
        "message": {
            "recipient": {"chat_id": 8000 + user_id, "chat_type": "dialog", "user_id": user_id},
            "body": {"mid": f"mid-consent-{user_id}", "text": ""},
        },
    }


async def _count_users(api, external_id: str) -> int:
    factory = api.app.state.session_factory
    async with factory() as session:
        found = await session.scalar(
            select(func.count())
            .select_from(AuthIdentity)
            .where(
                AuthIdentity.provider == BOT_PROVIDER,
                AuthIdentity.external_id == external_id,
            )
        )
    return int(found or 0)


async def test_consent_creates_one_user_and_does_not_enroll_without_a_class(seeded):
    api = seeded
    await post_update(api, _started(4242, "Ира"))
    assert await _count_users(api, "4242") == 0
    assert "согласие" in api.memory.sent[-1]["text"].casefold()

    await post_update(api, _consent(4242, "Ира"))
    again = _consent(4242, "Ира")
    again["callback"]["callback_id"] = "consent-4242-again"
    await post_update(api, again)
    assert await _count_users(api, "4242") == 1

    factory = api.app.state.session_factory
    async with factory() as session:
        user = await session.scalar(
            select(User)
            .join(AuthIdentity, AuthIdentity.user_id == User.id)
            .where(AuthIdentity.external_id == "4242")
        )
        from app.db.models import Enrollment

        enrolled = await session.scalar(
            select(func.count()).select_from(Enrollment).where(Enrollment.user_id == user.id)
        )
    assert user.role == "student"
    assert int(enrolled or 0) == 0
    await auth_as(api, "900001")
    report = await api.client.get("/api/teacher/class")
    assert report.status_code == 200
    assert "Ира" not in report.text


async def test_start_payload_joins_only_after_consent(seeded):
    api = seeded
    await auth_as(api, "900001")
    await post_update(api, _started(5151, "Петя", "8b-demo"))
    await post_update(api, _consent(5151, "Петя"))
    report = await api.client.get("/api/teacher/class")
    assert report.status_code == 200
    assert "Петя" in report.text


async def test_init_data_user_id_is_not_the_bot_user(seeded):
    api = seeded
    response = await api.client.post(
        "/api/session",
        json={"init_data": sign_init_data(900002, api.settings.max_token or "", "Алексей")},
    )
    assert response.status_code == 403
    factory = api.app.state.session_factory
    async with factory() as session:
        linked = await session.scalar(
            select(func.count())
            .select_from(AuthIdentity)
            .where(AuthIdentity.provider == WEBAPP_PROVIDER, AuthIdentity.external_id == "900002")
        )
    assert int(linked or 0) == 0


async def test_teacher_code_is_single_use_and_student_cannot_open_the_cabinet(seeded):
    api = seeded
    await post_update(api, message(900001, "Марина", "Войти в кабинет", "code-1"))
    text = api.memory.sent[-1]["text"]
    found = re.search(r"\d{6}", text)
    assert found is not None
    code = found.group(0)
    first = await api.client.post("/api/web-login", json={"code": code})
    assert first.status_code == 200, first.text
    report = await api.client.get("/api/teacher/class")
    assert report.status_code == 200
    again = await api.client.post("/api/web-login", json={"code": code})
    assert again.status_code == 401

    await post_update(api, message(900002, "Алексей", "Войти в кабинет", "code-student"))
    assert "учител" in api.memory.sent[-1]["text"].casefold()


async def test_login_attempt_limit(seeded):
    api = seeded
    for index in range(4):
        response = await api.client.post("/api/web-login", json={"code": f"11111{index}"})
        assert response.status_code == 401
    blocked = await api.client.post("/api/web-login", json={"code": "000000"})
    assert blocked.status_code == 429


async def test_teachers_do_not_see_each_others_classes(seeded):
    api = seeded
    factory = api.app.state.session_factory
    async with factory() as session:
        school = await add_school(session, "Вторая школа")
        other = await add_class(session, school.id, "9А")
        await accept_consent(session, "700001", "Второй учитель", api.settings)
        from app.db.models import ClassTeacher

        teacher = await session.scalar(
            select(User)
            .join(AuthIdentity, AuthIdentity.user_id == User.id)
            .where(AuthIdentity.external_id == "700001")
        )
        teacher.role = "teacher"
        session.add(ClassTeacher(class_id=other.id, user_id=teacher.id))
        other_id = other.id
        await session.commit()
    await auth_as(api, "900001")
    forbidden = await api.client.get("/api/teacher/class", params={"class_id": other_id})
    assert forbidden.status_code == 403
    own = await api.client.get("/api/teacher/class")
    assert own.status_code == 200
    assert "9А" not in own.text
    assert "Второй учитель" not in own.text


async def test_blocked_user_is_refused_and_kept(seeded):
    api = seeded
    factory = api.app.state.session_factory
    async with factory() as session:
        user = await session.scalar(
            select(User)
            .join(AuthIdentity, AuthIdentity.user_id == User.id)
            .where(AuthIdentity.external_id == "900004")
        )
        await set_blocked(session, user.id, True, None)
        await session.commit()
        user_id = user.id
    before = await _attempts(api, user_id)
    await post_update(api, message(900004, "Кирилл", "дроби", "blocked-1"))
    assert "закрыт" in api.memory.sent[-1]["text"].casefold()
    assert await _attempts(api, user_id) == before
    await auth_as(api, "900004")
    progress = await api.client.get("/api/student/progress")
    assert progress.status_code == 403


async def test_delete_removes_the_profile_and_keeps_an_audit_fact(seeded):
    api = seeded
    factory = api.app.state.session_factory
    async with factory() as session:
        user = await accept_consent(session, "6161", "Секретное Имя", api.settings)
        await session.commit()
        user_id = user.id
    async with factory() as session:
        assert await delete_user_data(session, user_id, None)
        await session.commit()
    async with factory() as session:
        left = await session.get(User, user_id)
        from app.db.models import AuditLog

        fact = await session.scalar(
            select(AuditLog).where(AuditLog.action == "delete_user", AuditLog.target_user_id == user_id)
        )
    assert left is None
    assert fact is not None
    assert "Секретное" not in (fact.detail or "")


async def test_group_chat_is_ignored(seeded):
    api = seeded
    payload = message(4243, "Ира", "дроби", "group-1")
    payload["message"]["recipient"]["chat_type"] = "chat"
    before = len(api.memory.sent)
    await post_update(api, payload)
    assert len(api.memory.sent) == before
    assert await _count_users(api, "4243") == 0


async def test_database_down_replies_without_creating_a_user(seeded):
    api = seeded
    api.app.state.session_factory = None
    response = await api.client.post(
        "/webhook",
        json=message(4244, "Ира", "дроби", "down-1"),
        headers={"X-Max-Bot-Api-Secret": api.settings.max_webhook_secret or ""},
    )
    assert response.status_code == 200
    assert "через минуту" in api.memory.sent[-1]["text"]


async def test_class_rows_are_scoped(seeded):
    api = seeded
    factory = api.app.state.session_factory
    async with factory() as session:
        titles = list(await session.scalars(select(SchoolClass.title)))
    assert titles == ["8Б"]


async def test_teacher_request_does_not_open_the_cabinet(seeded):
    api = seeded
    await post_update(api, message(900002, "Алексей", "Я учитель", "apply-1"))
    await post_update(api, message(900002, "Алексей", "Иванов Алексей", "apply-2"))
    await post_update(api, message(900002, "Алексей", "Школа 1", "apply-3"))
    factory = api.app.state.session_factory
    async with factory() as session:
        user = await session.scalar(
            select(User)
            .join(AuthIdentity, AuthIdentity.user_id == User.id)
            .where(AuthIdentity.external_id == "900002")
        )
        application = await session.get(TeacherApplication, user.id)
        assert user.role == "student"
        assert application.status == "pending"
        await approve_teacher(session, user.id, None)
        await session.commit()
        await session.refresh(user)
        assert user.role == "teacher"
    await post_update(api, message(900002, "Алексей", "Войти в кабинет", "apply-4"))
    found = re.search(r"\d{6}", api.memory.sent[-1]["text"])
    assert found is not None


async def test_transfer_keeps_history_on_the_old_profile(seeded):
    api = seeded
    factory = api.app.state.session_factory
    async with factory() as session:
        old = await session.scalar(
            select(User)
            .join(AuthIdentity, AuthIdentity.user_id == User.id)
            .where(AuthIdentity.external_id == "900002")
        )
        lesson = LearningSession(
            user_id=old.id,
            mode="training",
            step="done",
            example_index=0,
            task_index=0,
            created_at=datetime.now(UTC),
        )
        session.add(lesson)
        await session.flush()
        session.add(
            Attempt(
                user_id=old.id,
                topic_id=1,
                session_id=lesson.id,
                mode="training",
                prompt="1+1",
                expected="2",
                answer="2",
                correct=True,
                feedback="Верно.",
                created_at=old.created_at,
            )
        )
        code = await create_transfer(session, old.id, None, api.settings)
        await session.commit()
        old_id = old.id
    await post_update(api, _started(8181, "Новый"))
    await post_update(api, _consent(8181, "Новый"))
    await post_update(api, message(8181, "Новый", code, "transfer-1"))
    async with factory() as session:
        moved = await session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.provider == BOT_PROVIDER,
                AuthIdentity.external_id == "8181",
            )
        )
        kept = await session.scalar(
            select(func.count()).select_from(Attempt).where(Attempt.user_id == old_id)
        )
    assert moved is not None
    assert moved.user_id == old_id
    assert moved.revoked_at is None
    assert int(kept or 0) == 1


async def _attempts(api, user_id: int) -> int:
    factory = api.app.state.session_factory
    async with factory() as session:
        found = await session.scalar(
            select(func.count()).select_from(Attempt).where(Attempt.user_id == user_id)
        )
    return int(found or 0)
