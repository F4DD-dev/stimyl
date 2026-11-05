"""Своя тема, сдача и имя в списке учителя."""

from datetime import UTC, datetime

from sqlalchemy import delete, select

from app.db.models import ClassTeacher, Topic, WorkAnswer, WorkRecipient
from tests.support import auth_as


async def test_custom_topic_shows_who_handed_it_in(seeded):
    api = seeded
    await auth_as(api, "900001")
    saved = await api.client.post(
        "/api/teacher/works",
        json={
            "topic": "Проценты",
            "goal": "Найти процент от числа",
            "count": 1,
            "difficulty": "normal",
            "audience": "selected",
            "students": ["Алексей"],
            "blurb": "Процент это сотая часть числа.",
            "items": [{"prompt": "20% от 50. Напиши число.", "reference": "10"}],
        },
    )
    assert saved.status_code == 200, saved.text
    published = await api.client.post(f"/api/teacher/works/{saved.json()['id']}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["recipients"] == 1

    await auth_as(api, "900002")
    works = await api.client.get("/api/student/works")
    assert works.status_code == 200, works.text
    item = works.json()["items"][0]
    assert item["title"] == "Проценты"
    assert "сотая часть" in item["study"]
    answered = await api.client.post(
        f"/api/student/works/{item['id']}/answers",
        json={"answers": [{"item_id": item["items"][0]["id"], "answer": "10"}]},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["status"] == "done"

    await auth_as(api, "900001")
    listed = await api.client.get("/api/teacher/assignments")
    assert listed.status_code == 200, listed.text
    row = next(work for work in listed.json()["items"] if work["title"] == "Проценты")
    assert row["done"] == 1
    assert row["handed"] == ["Алексей"]

    report = await api.client.get("/api/teacher/class")
    student = next(person for person in report.json()["students"] if person["display_name"] == "Алексей")
    assert any(topic["title"] == "Проценты" and topic["status"] for topic in student["topics"])
    assert "10" not in student["activity"]


async def test_listing_repairs_a_finished_answer(seeded):
    api = seeded
    await auth_as(api, "900001")
    saved = await api.client.post(
        "/api/teacher/works",
        json={
            "topic": "Дроби",
            "goal": "Общий знаменатель",
            "count": 1,
            "difficulty": "easy",
            "audience": "selected",
            "students": ["Аня"],
        },
    )
    assert saved.status_code == 200, saved.text
    work_id = saved.json()["id"]
    item_id = saved.json()["items"][0]["id"]
    published = await api.client.post(f"/api/teacher/works/{work_id}/publish")
    assert published.status_code == 200, published.text

    factory = api.app.state.session_factory
    async with factory() as session:
        recipient = await session.scalar(select(WorkRecipient).where(WorkRecipient.work_id == work_id))
        session.add(
            WorkAnswer(
                work_id=work_id,
                item_id=item_id,
                user_id=recipient.user_id,
                answer="1/2",
                correct=True,
                created_at=datetime.now(UTC),
            )
        )
        recipient.status = "assigned"
        await session.commit()

    await auth_as(api, "900001")
    listed = await api.client.get("/api/teacher/assignments")
    row = next(work for work in listed.json()["items"] if work["id"] == work_id)
    assert row["done"] == 1
    assert "Аня" in row["handed"]


async def test_stimul_refuses_a_topic_outside_the_programme(seeded):
    api = seeded
    await auth_as(api, "900001")
    refused = await api.client.post(
        "/api/teacher/drafts",
        json={
            "topic": "История Древнего мира",
            "goal": "Даты",
            "count": 1,
            "difficulty": "easy",
            "audience": "class",
        },
    )
    assert refused.status_code == 409
    made = await api.client.post(
        "/api/teacher/drafts",
        json={
            "topic": "Сложение дробей",
            "goal": "Общий знаменатель",
            "count": 1,
            "difficulty": "easy",
            "audience": "class",
        },
    )
    assert made.status_code == 200, made.text
    assert made.json()["items"][0]["reference"]
    async with api.app.state.session_factory() as session:
        stored = await session.scalar(select(Topic).where(Topic.title == "Сложение дробей"))
    assert stored is None


async def test_class_without_a_teacher_has_no_assignments(seeded):
    api = seeded
    await auth_as(api, "900001")
    saved = await api.client.post(
        "/api/teacher/works",
        json={
            "topic": "Дроби",
            "goal": "Общий знаменатель",
            "count": 1,
            "difficulty": "easy",
            "audience": "selected",
            "students": ["Алексей"],
        },
    )
    assert saved.status_code == 200, saved.text
    work_id = saved.json()["id"]
    item_id = saved.json()["items"][0]["id"]
    published = await api.client.post(f"/api/teacher/works/{work_id}/publish")
    assert published.status_code == 200, published.text

    factory = api.app.state.session_factory
    async with factory() as session:
        await session.execute(delete(ClassTeacher))
        await session.commit()

    await auth_as(api, "900002")
    works = await api.client.get("/api/student/works")
    assert works.status_code == 200, works.text
    assert works.json()["items"] == []
    assert works.json()["reason"] == "no_teacher"
    refused = await api.client.post(
        f"/api/student/works/{work_id}/answers",
        json={"answers": [{"item_id": item_id, "answer": "1/2"}]},
    )
    assert refused.status_code == 404


async def test_second_submit_does_not_create_another_attempt(seeded):
    api = seeded
    await auth_as(api, "900001")
    saved = await api.client.post(
        "/api/teacher/works",
        json={
            "topic": "Дроби",
            "goal": "Общий знаменатель",
            "count": 1,
            "difficulty": "easy",
            "audience": "selected",
            "students": ["Алексей"],
        },
    )
    work_id = saved.json()["id"]
    item_id = saved.json()["items"][0]["id"]
    assert (await api.client.post(f"/api/teacher/works/{work_id}/publish")).status_code == 200
    await auth_as(api, "900002")
    body = {"answers": [{"item_id": item_id, "answer": "1/2"}]}
    first = await api.client.post(f"/api/student/works/{work_id}/answers", json=body)
    assert first.status_code == 200, first.text
    second = await api.client.post(f"/api/student/works/{work_id}/answers", json=body)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "done"
    from app.db.models import Attempt

    async with api.app.state.session_factory() as session:
        count = len(list(await session.scalars(select(Attempt).where(Attempt.user_id.is_not(None)))))
    assert count == 1
