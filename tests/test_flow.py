from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db.models import Attempt, LearningSession, Message, User
from app.db.seed import seed
from tests.support import button_payload, callback, message, post_update, sign_init_data


async def test_seed_is_idempotent_and_roster_comes_from_the_database(api):
    factory = api.app.state.session_factory
    async with factory() as session:
        await seed(session)
        await session.commit()
    async with factory() as session:
        await seed(session)
        await session.commit()
        users = list(await session.scalars(select(User)))
        topics = list(await session.scalars(select(Message)))
    names = sorted(user.display_name for user in users)
    assert names.count("Алексей") == 1
    assert "Марина Сергеевна" in names
    assert topics == []
    async with factory() as session:
        from app.db.models import Topic

        titles = list(await session.scalars(select(Topic.title).order_by(Topic.position)))
    assert titles[0] == "Дроби"
    assert "Квадратные уравнения и дискриминант" in titles


async def _practice(api, user_id: int, name: str, question: str, answers: list[str]) -> None:
    await post_update(api, message(user_id, name, question, f"q-{user_id}"))
    await post_update(
        api,
        callback(user_id, name, f"cb-practice-{user_id}", button_payload(api, "К практике")),
    )
    for index, answer in enumerate(answers):
        await post_update(api, message(user_id, name, answer, f"a-{user_id}-{index}"))
        if index < len(answers) - 1:
            await post_update(
                api,
                callback(
                    user_id, name, f"cb-again-{user_id}-{index}", button_payload(api, "Ещё задание")
                ),
            )


async def test_training_updates_status_and_hides_private_text(seeded):
    api = seeded
    await _practice(api, 900002, "Алексей", "Помоги с катетом, страница 17+4", ["нет"])
    await _practice(api, 900003, "Аня", "Объясни дроби", ["1/2", "0.5"])
    await _practice(api, 900005, "Ольга", "линейные уравнения", ["5"])

    sent = "\n".join(item["text"] for item in api.memory.sent)
    assert "21" not in sent
    assert "17+4" not in sent

    factory = api.app.state.session_factory
    async with factory() as session:
        session.add(
            Message(
                session_id=(await session.scalar(select(LearningSession.id).limit(1))),
                role="student",
                text="СЕКРЕТ-ВОПРОС",
                visibility="private",
                created_at=datetime.now(UTC),
            )
        )
        attempt = await session.scalar(select(Attempt).limit(1))
        attempt.answer = "ТАЙНЫЙ-ОТВЕТ"
        learning = await session.scalar(select(LearningSession).limit(1))
        learning.photo_url = "https://files.example/secret-photo-9f3a"
        await session.commit()

    login = await api.client.post(
        "/api/session",
        json={"init_data": sign_init_data(900001, api.settings.max_token or "")},
    )
    assert login.status_code == 200
    report = await api.client.get("/api/teacher/class")
    assert report.status_code == 200
    body = report.text
    assert "mastered" in body
    assert "needs_practice" in body
    assert "repeat" in body
    for secret in ("17+4", "СЕКРЕТ-ВОПРОС", "ТАЙНЫЙ-ОТВЕТ", "secret-photo-9f3a"):
        assert secret not in body

    student = await api.client.post(
        "/api/session",
        json={"init_data": sign_init_data(900002, api.settings.max_token or "", "Алексей")},
    )
    assert student.status_code == 200
    progress = await api.client.get("/api/student/progress", params={"user_id": "900005"})
    assert progress.status_code == 200
    progress_body = progress.text
    assert "Алексей" in progress_body
    assert "Ольга" not in progress_body
    assert "Кирилл" not in progress_body
    assert "СЕКРЕТ-ВОПРОС" not in progress_body

    other = await api.client.get("/api/teacher/class")
    assert other.status_code == 403


async def test_duplicate_update_does_not_grade_twice(seeded):
    api = seeded
    payload = message(900004, "Кирилл", "линейные уравнения", "same-mid")
    await post_update(api, payload)
    await post_update(api, payload)
    texts = [item["text"] for item in api.memory.sent]
    assert len(texts) == 1
    factory = api.app.state.session_factory
    async with factory() as session:
        count = await session.scalar(select(func.count()).select_from(Attempt))
    assert count == 0


async def test_webhook_rejects_a_bad_secret(seeded):
    response = await seeded.client.post(
        "/webhook",
        json=message(900002, "Алексей", "дроби", "mid-secret"),
        headers={"X-Max-Bot-Api-Secret": "wrong-secret"},
    )
    assert response.status_code == 401


async def test_training_photo_does_not_invent_a_solution(seeded):
    photo = message(
        900004,
        "Кирилл",
        "",
        "mid-photo",
        images=[
            {
                "type": "image",
                "payload": {"photo_id": 1, "token": "tok", "url": "https://cdn.example/page.jpg"},
            }
        ],
    )
    photo["message"]["body"]["text"] = None
    await post_update(seeded, photo)
    text = seeded.memory.sent[-1]["text"]
    assert "Напиши тему" in text
    assert "21" not in text
