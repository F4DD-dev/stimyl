import asyncio
import hashlib
import hmac

from sqlalchemy import func, select

from app.db.models import (
    ClassSubjectTeacher,
    ClassTeacher,
    Enrollment,
    Subject,
    OutboundNotice,
    RuntimeFlag,
    User,
    Work,
    WorkRecipient,
)
from app.domain.accounts import accept_consent
from app.domain.onboarding import BOOTSTRAP_KEY, ensure_prototype, register_phone
from app.domain.phone import hash_phone, verify_contact_hash
from tests.support import auth_as, callback, message, post_update
from tests.test_accounts import _consent, _started


async def _click(api, user_id: int, name: str, marker: str, *, by_text: bool = False) -> None:
    buttons = api.memory.sent[-1]["buttons"]
    if by_text:
        payload = next(button["payload"] for button in buttons if button["text"] == marker)
    else:
        payload = next(button["payload"] for button in buttons if str(button["payload"]).startswith(marker))
    await post_update(api, callback(user_id, name, f"pick-{user_id}-{marker}", payload))


def _vcf(name: str, digits: str) -> str:
    return f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:{name}\r\nTEL;TYPE=CELL:+{digits}\r\nEND:VCARD"


def _contact(user_id: int, name: str, mid: str, digits: str, token: str, *, digest: str | None = None) -> dict:
    vcf = _vcf(name, digits)
    signed = digest if digest is not None else hmac.new(token.encode(), vcf.encode(), hashlib.sha256).hexdigest()
    payload = message(user_id, name, "", mid)
    payload["message"]["body"]["attachments"] = [
        {"type": "contact", "payload": {"vcf_info": vcf, "hash": signed}}
    ]
    return payload


async def test_old_role_and_consent_still_require_a_verified_contact(api):
    api.settings.first_teacher_bootstrap = True
    factory = api.app.state.session_factory
    async with factory() as session:
        user = await accept_consent(session, "840010", "Марк", api.settings)
        user.role = "teacher"
        user.can_manage_school = True
        school_class, _subject = await ensure_prototype(session)
        session.add(ClassTeacher(class_id=school_class.id, user_id=user.id))
        await session.commit()

    await post_update(api, message(840010, "Марк", "привет", "old-role"))
    buttons = api.memory.sent[-1]["buttons"]
    assert any(button.get("type") == "request_contact" for button in buttons)
    assert "учитель-администратор" not in api.memory.sent[-1]["text"].casefold()
    async with factory() as session:
        stored = await session.scalar(select(User).where(User.display_name == "Марк"))
        flag = await session.get(RuntimeFlag, BOOTSTRAP_KEY)
        assert stored is not None
        assert stored.phone_hash is None
        assert stored.role == "teacher"
        assert flag is None or flag.value == "open"

    token = api.settings.max_token or ""
    await post_update(api, _contact(840010, "Марк", "mark-old-role", "79004440010", token))
    async with factory() as session:
        stored = await session.scalar(select(User).where(User.display_name == "Марк"))
        flag = await session.get(RuntimeFlag, BOOTSTRAP_KEY)
        assert stored is not None
        assert stored.phone_hash is not None
        assert flag is None or flag.value == "open"


async def test_active_enrollment_without_a_phone_still_asks_for_contact(api):
    factory = api.app.state.session_factory
    async with factory() as session:
        user = await accept_consent(session, "840011", "Оля", api.settings)
        school_class, _subject = await ensure_prototype(session)
        session.add(Enrollment(class_id=school_class.id, user_id=user.id, status="active"))
        await session.commit()

    await post_update(api, message(840011, "Оля", "Объясни дроби", "placed-no-phone"))
    buttons = api.memory.sent[-1]["buttons"]
    assert any(button.get("type") == "request_contact" for button in buttons)
    async with factory() as session:
        stored = await session.scalar(select(User).where(User.display_name == "Оля"))
        assert stored is not None
        assert stored.phone_hash is None
        assert stored.role == "student"
        assert stored.can_manage_school is False


async def test_bootstrap_starts_only_after_a_verified_contact(api):
    api.settings.first_teacher_bootstrap = True
    token = api.settings.max_token or ""
    await post_update(api, _started(840012, "Ира"))
    await post_update(api, _consent(840012, "Ира"))
    buttons = api.memory.sent[-1]["buttons"]
    assert any(button.get("type") == "request_contact" for button in buttons)
    factory = api.app.state.session_factory
    async with factory() as session:
        stored = await session.scalar(select(User).where(User.display_name == "Ира"))
        flag = await session.get(RuntimeFlag, BOOTSTRAP_KEY)
        assert stored is not None
        assert stored.role == "student"
        assert stored.can_manage_school is False
        assert stored.phone_hash is None
        assert flag is None or flag.value == "open"

    await post_update(api, _contact(840012, "Ира", "ira-bad", "79004440012", "wrong-token"))
    async with factory() as session:
        stored = await session.scalar(select(User).where(User.display_name == "Ира"))
        assert stored is not None
        assert stored.phone_hash is None
        assert stored.can_manage_school is False

    await post_update(api, _contact(840012, "Ира", "ira-good", "79004440012", token))
    assert any("учитель-администратор" in item["text"].casefold() for item in api.memory.sent)
    async with factory() as session:
        stored = await session.scalar(select(User).where(User.display_name == "Ира"))
        flag = await session.get(RuntimeFlag, BOOTSTRAP_KEY)
        assert stored is not None
        assert stored.role == "teacher"
        assert stored.can_manage_school is True
        assert stored.phone_hash is not None
        assert flag is not None
        assert flag.value == "consumed"


def test_contact_hash_rejects_a_forwarded_card_and_a_wrong_token():
    vcf = _vcf("Оля", "79001234567")
    assert verify_contact_hash(vcf, "", "token") is False
    assert verify_contact_hash(vcf, "abcd", "token") is False
    good = hmac.new(b"token", vcf.encode(), hashlib.sha256).hexdigest()
    assert verify_contact_hash(vcf, good, "token") is True
    assert verify_contact_hash(vcf, good, "other") is False


async def test_text_phone_and_bad_contact_do_not_create_a_claim(api):
    await post_update(api, _started(61001, "Оля"))
    await post_update(api, _consent(61001, "Оля"))
    await post_update(api, message(61001, "Оля", "+79001112233", "phone-text"))
    assert "текстом" in api.memory.sent[-1]["text"].casefold()
    await post_update(api, _contact(61001, "Оля", "bad-hash", "79001112233", "nope"))
    assert "не подтвержд" in api.memory.sent[-1]["text"].casefold()
    factory = api.app.state.session_factory
    async with factory() as session:
        user = await session.scalar(select(User).where(User.display_name == "Оля"))
        assert user is not None
        assert user.phone_hash is None
        assert user.role == "student"


async def test_only_one_concurrent_registration_becomes_teacher(api):
    api.settings.first_teacher_bootstrap = True
    factory = api.app.state.session_factory
    async with factory() as session:
        first = await accept_consent(session, "810001", "Марк", api.settings)
        second = await accept_consent(session, "810002", "Оля", api.settings)
        await session.commit()
        first_id, second_id = first.id, second.id

    async def once(user_id: int, digits: str) -> str:
        async with factory() as session:
            user = await session.get(User, user_id)
            result = await register_phone(session, user, digits, api.settings)
            await session.commit()
            return result.kind

    kinds = await asyncio.gather(once(first_id, "79001110001"), once(second_id, "79001110002"))
    assert sorted(kinds) == ["choose", "teacher"]
    async with factory() as session:
        flag = await session.get(RuntimeFlag, BOOTSTRAP_KEY)
        teachers = list(await session.scalars(select(User).where(User.can_manage_school.is_(True))))
        assert flag is not None
        assert flag.value == "consumed"
        assert len(teachers) == 1
        assert teachers[0].role == "teacher"
        posts = await session.scalar(select(func.count()).select_from(ClassSubjectTeacher))
        assert int(posts or 0) == 1
        teacher = teachers[0]
        teacher.can_manage_school = False
        teacher.deleted_at = teacher.created_at
        await session.commit()
        third = await accept_consent(session, "810003", "Петя", api.settings)
        await session.commit()
        third_id = third.id
    async with factory() as session:
        user = await session.get(User, third_id)
        result = await register_phone(session, user, "79001110003", api.settings)
        await session.commit()
    assert result.kind == "choose"
    async with factory() as session:
        flag = await session.get(RuntimeFlag, BOOTSTRAP_KEY)
        bosses = await session.scalar(
            select(func.count()).select_from(User).where(User.can_manage_school.is_(True))
        )
    assert flag.value == "consumed"
    assert int(bosses or 0) == 0


async def test_production_never_bootstraps_a_teacher(api):
    api.settings.env = "prod"
    api.settings.first_teacher_bootstrap = True
    factory = api.app.state.session_factory
    async with factory() as session:
        user = await accept_consent(session, "820001", "Ира", api.settings)
        await session.commit()
        user_id = user.id
    async with factory() as session:
        user = await session.get(User, user_id)
        result = await register_phone(session, user, "79002220001", api.settings)
        await session.commit()
        flag = await session.get(RuntimeFlag, BOOTSTRAP_KEY)
        stored = await session.get(User, user_id)
    assert result.kind == "choose"
    assert stored.role == "student"
    assert stored.can_manage_school is False
    assert stored.phone_hash == hash_phone(api.settings.session_secret, "79002220001")
    assert stored.phone_mask.endswith("00-01")
    assert "79002220001" not in (stored.phone_mask or "")
    assert flag.value == "open"


async def test_claim_accept_publishes_work_without_a_stale_ticket(seeded):
    api = seeded
    api.settings.first_teacher_bootstrap = True
    api.settings.bot_username = "ideya_fiks_101_bot"
    api.settings.bot_contact_id = 387830563
    token = api.settings.max_token or ""
    await post_update(api, _started(830001, "Марк"))
    await post_update(api, _consent(830001, "Марк"))
    await post_update(api, _contact(830001, "Марк", "mark-phone", "79003330001", token))
    joined = "\n".join(item["text"] for item in api.memory.sent)
    assert "учитель-администратор" in joined.casefold()
    await post_update(api, _started(830002, "Оля"))
    await post_update(api, _consent(830002, "Оля"))
    await post_update(api, _contact(830002, "Оля", "olya-phone", "79003330002", token))
    assert "кто ты" in api.memory.sent[-1]["text"].casefold()
    await _click(api, 830002, "Оля", "role:student")
    await _click(api, 830002, "Оля", "city:0")
    await _click(api, 830002, "Оля", "school:blg-16")
    await _click(api, 830002, "Оля", "8Б", by_text=True)
    assert "заявк" in api.memory.sent[-1]["text"].casefold()
    assert any(button.get("web_app") for button in api.memory.sent[-1]["buttons"])

    await auth_as(api, "830001")
    people = await api.client.get("/api/manage/people")
    assert people.status_code == 200
    assert all("7900" not in item.get("phone_mask", "") for item in people.json()["items"])
    claims = await api.client.get("/api/manage/claims")
    assert claims.status_code == 200
    claim = claims.json()["items"][0]
    assert claim["display_name"] == "Оля"
    assert claim["class_title"] == "8Б"
    accepted = await api.client.post(f"/api/manage/claims/{claim['user_id']}/accept")
    assert accepted.status_code == 200, accepted.text

    forbidden = await api.client.get("/api/student/progress")
    assert forbidden.status_code == 403

    async with factory() as session:
        teacher = await session.scalar(select(User).where(User.display_name == "Марк"))
        subject = await session.scalar(select(Subject).where(Subject.title == "Математика"))
        session.add(ClassTeacher(class_id=claim["class_id"], user_id=teacher.id))
        session.add(
            ClassSubjectTeacher(
                class_id=claim["class_id"],
                user_id=teacher.id,
                subject_id=subject.id,
            )
        )
        await session.commit()

    draft = await api.client.post(
        "/api/teacher/works",
        json={
            "topic": "Дроби",
            "goal": "Проверить общий знаменатель",
            "count": 1,
            "difficulty": "normal",
            "audience": "selected",
            "students": ["Оля"],
            "class_id": claim["class_id"],
        },
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["persisted"] is True
    assert "reference" in draft.json()["items"][0]
    published = await api.client.post(f"/api/teacher/works/{draft.json()['id']}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["recipients"] == 1

    factory = api.app.state.session_factory
    async with factory() as session:
        outbound = list(await session.scalars(select(OutboundNotice).order_by(OutboundNotice.id)))
    assert outbound
    assert all("open_app" not in row.button_payload for row in outbound)
    assert all(row.button_payload in {"", "progress", f"open_work:{draft.json()['id']}"} for row in outbound)
    assert any(row.button_payload == f"open_work:{draft.json()['id']}" for row in outbound)
    assert all("ticket" not in row.body for row in outbound)

    from app.bot.delivery import send_pending_notices

    async with factory() as session:
        await send_pending_notices(session, api.memory)
        await session.commit()
    sent = [item for item in api.memory.sent if "Открыть задание" in item["text"] or any(
        button.get("text") == "Открыть задание" for button in item["buttons"]
    )]
    assert sent
    button = next(button for button in sent[-1]["buttons"] if button["text"] == "Открыть задание")
    assert button.get("web_app", "") == ""
    assert button["payload"].startswith("open_work:")

    await auth_as(api, "830002")
    works = await api.client.get("/api/student/works")
    assert works.status_code == 200, works.text
    item = works.json()["items"][0]
    assert "reference" not in item["items"][0]
    answered = await api.client.post(
        f"/api/student/works/{item['id']}/answers",
        json={"answers": [{"item_id": item["items"][0]["id"], "answer": "1/2"}]},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["persisted"] is True
    assert answered.json()["items"][0]["correct"] is True

    await auth_as(api, "900002")
    hidden = await api.client.get("/api/student/works")
    assert hidden.status_code == 200
    assert hidden.json()["items"] == []
    foreign = await api.client.get(f"/api/teacher/works/{item['id']}")
    assert foreign.status_code == 403

    async with factory() as session:
        stored = await session.get(Work, item["id"])
        recipient = await session.scalar(select(WorkRecipient).where(WorkRecipient.work_id == item["id"]))
    assert stored.status == "published"
    assert recipient.status == "done"
