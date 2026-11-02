from sqlalchemy import func, select

from app.db.models import LearningSession, Message
from tests.support import auth_as


async def login(api, user_id: int, name: str):
    await auth_as(api, str(user_id))
    return name


async def test_pages_and_assets_load(api):
    student = await api.client.get("/student")
    root = await api.client.get("/")
    css = await api.client.get("/assets/styles.css")
    script = await api.client.get("/assets/js/api.js")
    assert student.status_code == 200
    assert 'data-entry="student"' in student.text
    assert 'src="https://st.max.ru/js/max-web-app.js"' in student.text
    assert "max-web-app.js\" async" not in student.text
    assert 'data-entry="auto"' in root.text
    assert css.status_code == 200
    assert "#5b5cf0" in css.text
    assert "#c9f56b" in css.text
    assert script.status_code == 200
    assert "/api/student/practice" in script.text
    head = await api.client.head("/student")
    assert head.status_code == 200


async def test_training_checks_the_answer_and_hides_the_question(seeded):
    api = seeded
    await login(api, 900002, "Алексей")
    opened = await api.client.post(
        "/api/student/practice",
        json={"mode": "training", "text": "Как решить 17+4, линейные уравнения"},
    )
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["topic"] == "Линейные уравнения"
    assert body["explanation"]
    assert body["example"]
    assert "17+4" not in opened.text
    assert "expected" not in body
    assert "reference" not in body

    practiced = await api.client.post("/api/student/practice", json={"action": "to_practice"})
    assert practiced.status_code == 200, practiced.text
    assert practiced.json()["awaiting_answer"] is True
    lesson = await api.client.get("/api/student/lesson")
    assert lesson.status_code == 200
    assert lesson.json()["task"]
    assert lesson.json()["feedback"] is None
    factory = api.app.state.session_factory
    async with factory() as session:
        expected = await session.scalar(
            select(LearningSession.pending_answer).where(LearningSession.pending_answer.is_not(None))
        )
    assert expected

    graded = await api.client.post("/api/student/practice", json={"text": "нет-ТАЙНА"})
    assert graded.status_code == 200, graded.text
    graded_body = graded.json()
    assert graded_body["correct"] is False
    assert expected not in (graded_body["feedback"] or "")
    assert "expected" not in graded_body
    assert "нет-ТАЙНА" == graded_body["given"]

    progress = await api.client.get("/api/student/progress")
    assert progress.status_code == 200
    payload = progress.json()
    assert payload["class_title"] == "8Б"
    assert payload["display_name"] == "Алексей"
    assert payload["next_topic"]
    linear = next(item for item in payload["topics"] if item["title"] == "Линейные уравнения")
    assert linear["status"] == "started"
    assert linear["correct_percent"] is None
    assert "Ольга" not in progress.text
    assert "17+4" not in progress.text

    history = await api.client.get("/api/student/history")
    assert history.status_code == 200
    assert "17+4" not in history.text
    assert "нет-ТАЙНА" not in history.text
    assert history.json()["sessions"][0]["answered"] == 1
    factory = api.app.state.session_factory
    async with factory() as session:
        visibility = set(await session.scalars(select(Message.visibility)))
    assert visibility == {"private"}

    await login(api, 900001, "Марина")
    report = await api.client.get("/api/teacher/class")
    assert report.status_code == 200
    assert "started" in report.text
    for secret in ("17+4", "нет-ТАЙНА", "СЕКРЕТ"):
        assert secret not in report.text
    denied = await api.client.get("/api/student/progress")
    assert denied.status_code == 403


async def test_submission_does_not_store_the_question(seeded):
    api = seeded
    await login(api, 900002, "Алексей")
    response = await api.client.post(
        "/api/student/practice",
        json={"mode": "submission", "text": "СЕКРЕТ-СДАЧА"},
    )
    assert response.status_code == 409
    assert "СЕКРЕТ-СДАЧА" not in response.text
    assert "тренир" in response.text.casefold()
    factory = api.app.state.session_factory
    async with factory() as session:
        messages = await session.scalar(select(func.count()).select_from(Message))
    assert messages == 0


async def test_photo_is_accepted_and_not_solved(seeded):
    api = seeded
    await login(api, 900004, "Кирилл")
    response = await api.client.post(
        "/api/student/practice/photo",
        files={"photo": ("page.jpg", b"\xff\xd8\xff" + b"\x00" * 24, "image/jpeg")},
        data={"text": "линейные уравнения", "mode": "training"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["photo_received"] is True
    assert body["explanation"]
    assert "page.jpg" not in response.text
    assert "17+4" not in response.text
    factory = api.app.state.session_factory
    async with factory() as session:
        row = await session.scalar(select(LearningSession).order_by(LearningSession.id.desc()))
    assert row is not None
    assert row.photo_url is None
    assert row.photo_token is None

    rejected = await api.client.post(
        "/api/student/practice/photo",
        files={"photo": ("notes.txt", b"this is plain text, not a photo", "text/plain")},
        data={"mode": "training"},
    )
    assert rejected.status_code == 415


async def test_teacher_draft_is_not_a_delivery(seeded):
    api = seeded
    await login(api, 900002, "Алексей")
    forbidden = await api.client.post(
        "/api/teacher/drafts",
        json={
            "topic": "Дроби",
            "goal": "Проверить общий знаменатель",
            "count": 2,
            "difficulty": "normal",
            "audience": "class",
        },
    )
    assert forbidden.status_code == 403

    await login(api, 900001, "Марина")
    material = await api.client.post(
        "/api/teacher/drafts",
        json={
            "topic": "Дроби",
            "goal": "По параграфу",
            "count": 2,
            "difficulty": "normal",
            "audience": "class",
            "use_material": True,
        },
    )
    assert material.status_code == 409
    assert "фрагмент" in material.text

    draft = await api.client.post(
        "/api/teacher/drafts",
        json={
            "topic": "Дроби",
            "goal": "Проверить общий знаменатель",
            "count": 2,
            "difficulty": "normal",
            "audience": "selected",
            "students": ["Аня"],
        },
    )
    assert draft.status_code == 200, draft.text
    payload = draft.json()
    assert payload["persisted"] is False
    assert payload["source"] == "bank"
    assert payload["students"] == ["Аня"]
    assert payload["items"][0]["reference"]

    sent = await api.client.post(
        "/api/teacher/assignments",
        json={
            "topic": "Дроби",
            "goal": "Проверить общий знаменатель",
            "count": 2,
            "difficulty": "normal",
            "audience": "class",
        },
    )
    assert sent.status_code == 501
    assert "не ушёл" in sent.text
    listing = await api.client.get("/api/teacher/assignments")
    assert listing.status_code == 200
    assert listing.json()["items"] == []
