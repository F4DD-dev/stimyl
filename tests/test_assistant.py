"""ИИ-путь бота: разбор вопроса ученика, фото, черновик и отправка работы учителем.
Код решает, что показать; модель не судья ответа и не публикатор работы."""

import pytest
from sqlalchemy import func, select

from app.bot.compose import MATERIAL_MISSING, compose_draft
from app.db.models import Material, OutboundNotice, Work, WorkItem
from app.domain.assist import (
    LessonDraft,
    TaskDraft,
    TeacherAsk,
    leaks,
    match_students,
)
from app.domain.library import find_fragments, save_material
from app.llm.client import loads_object
from tests.support import button_payload, callback, message, post_update

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 60


class FakeTutor:
    """Ответы модели задаёт тест. Запоминает, что ей передали."""

    enabled = True

    def __init__(self) -> None:
        self.analyze_draft: LessonDraft | None = None
        self.analyze_calls: list[dict] = []
        self.teacher_ask: TeacherAsk | None = None
        self.teacher_calls: list[dict] = []
        self.work_items: list[tuple[TaskDraft, bool]] | None = None
        self.draft_calls: list[dict] = []

    async def explain_topic(self, topic_title):
        return None

    async def explain_mistake(self, topic_title, hint, *, prompt="", answer=""):
        return None

    async def read_photo(self, image, mime):
        return None

    async def analyze(self, question, topics, fragments, history, image=None):
        self.analyze_calls.append(
            {
                "question": question,
                "topics": list(topics),
                "fragments": list(fragments),
                "history": list(history),
                "image": image,
            }
        )
        return self.analyze_draft

    async def confirm(self, task):
        return True

    async def make_task(self, topic, level, fragments):
        return None

    async def draft_work(self, topic, goal, count, difficulty, fragments):
        self.draft_calls.append(
            {"topic": topic, "goal": goal, "count": count, "fragments": list(fragments)}
        )
        return self.work_items

    async def read_teacher(self, text, topics):
        self.teacher_calls.append({"text": text, "topics": list(topics)})
        return self.teacher_ask


@pytest.fixture
def tutor(api):
    fake = FakeTutor()
    api.app.state.explainer = fake
    return fake


async def test_student_question_goes_to_model_and_stays_private(seeded, tutor):
    tutor.analyze_draft = LessonDraft(
        topic="Дроби",
        explanation="Сложи числители, когда знаменатели одинаковые.",
        example="1/5 + 2/5 = 3/5",
        task=TaskDraft(prompt="Вычисли 1/7 + 3/7", answer="4/7"),
        original_answer="4/7",
    )
    await post_update(seeded, message(900002, "Алексей", "как сложить дроби?", "q-1"))
    call = tutor.analyze_calls[0]
    assert call["question"] == "как сложить дроби?"
    assert "Алексей" not in call["question"]
    assert "900002" not in call["question"]
    assert "Дроби" in call["topics"]
    texts = [item["text"] for item in seeded.memory.sent]
    assert any("Сложи числители" in text for text in texts)


async def test_student_photo_is_downloaded_and_shown_to_model(seeded, tutor, monkeypatch):
    downloaded = []

    async def fake_download(url):
        downloaded.append(url)
        return PNG

    monkeypatch.setattr(seeded.memory, "download", fake_download, raising=False)
    tutor.analyze_draft = LessonDraft(
        topic="Дроби",
        explanation="На фото задача про дроби. Сначала приведи к общему знаменателю.",
        example="",
        task=None,
        original_answer="",
    )
    images = [{"type": "image", "payload": {"url": "https://files.example/p.png"}}]
    await post_update(seeded, message(900003, "Аня", "", "p-1", images=images))
    assert downloaded == ["https://files.example/p.png"]
    call = tutor.analyze_calls[0]
    blob, mime = call["image"]
    assert blob.startswith(b"\x89PNG")
    assert mime == "image/png"
    texts = [item["text"] for item in seeded.memory.sent]
    assert any("общему знаменателю" in text for text in texts)


async def test_photo_marked_unreadable_gets_honest_reply(seeded, tutor, monkeypatch):
    async def fake_download(url):
        return PNG

    monkeypatch.setattr(seeded.memory, "download", fake_download, raising=False)
    tutor.analyze_draft = LessonDraft(
        topic=None, explanation="", example="", task=None, unreadable=True
    )
    images = [{"type": "image", "payload": {"url": "https://files.example/blur.png"}}]
    await post_update(seeded, message(900003, "Аня", "", "p-2", images=images))
    assert seeded.memory.sent
    assert all("Ответ:" not in item["text"] for item in seeded.memory.sent)


async def test_explanation_leaking_answer_is_replaced(seeded, tutor):
    tutor.analyze_draft = LessonDraft(
        topic="Дроби",
        explanation="Просто сложи и получится ответ: 4/7",
        example="",
        task=None,
        original_answer="4/7",
    )
    await post_update(seeded, message(900002, "Алексей", "реши 1/7 + 3/7", "q-2"))
    texts = "\n".join(item["text"] for item in seeded.memory.sent)
    assert "ответ: 4/7" not in texts.casefold()


async def test_teacher_draft_send_publishes_work(seeded, tutor):
    tutor.teacher_ask = TeacherAsk(intent="work", topic="Дроби", goal="сложение", count=2)
    tutor.work_items = [
        (TaskDraft(prompt="Вычисли 1/2 + 1/4", answer="3/4"), True),
        (TaskDraft(prompt="Вычисли 2/3 - 1/6", answer="1/2"), True),
    ]
    await post_update(
        seeded, message(900001, "Марина Сергеевна", "Собери проверку по дробям", "t-1")
    )
    preview = seeded.memory.sent[-1]
    assert "Черновик" in preview["text"]
    assert "Ответ: 3/4" in preview["text"]
    payload = button_payload(seeded, "Отправить классу")
    assert payload and payload.startswith("tw_send:")
    await post_update(seeded, callback(900001, "Марина Сергеевна", "cb-1", payload))
    done = seeded.memory.sent[-1]["text"]
    assert "Отправил" in done
    factory = seeded.app.state.session_factory
    async with factory() as session:
        work = await session.scalar(select(Work).order_by(Work.id.desc()))
        assert work is not None and work.status == "published"
        items = await session.scalar(
            select(func.count()).select_from(WorkItem).where(WorkItem.work_id == work.id)
        )
        assert items == 2
        notices = await session.scalar(
            select(func.count())
            .select_from(OutboundNotice)
            .where(OutboundNotice.kind == "work", OutboundNotice.ref_id == work.id)
        )
        assert notices == 4


async def test_teacher_cannot_send_another_teachers_work(seeded, tutor):
    tutor.teacher_ask = TeacherAsk(intent="work", topic="Дроби", goal="дроби", count=1)
    tutor.work_items = [(TaskDraft(prompt="1/2 + 1/2", answer="1"), True)]
    await post_update(seeded, message(900001, "Марина Сергеевна", "проверка", "t-2"))
    payload = button_payload(seeded, "Отправить классу")
    work_id = int(payload.split(":")[1])
    await post_update(seeded, callback(900002, "Алексей", "cb-2", f"tw_send:{work_id}"))
    factory = seeded.app.state.session_factory
    async with factory() as session:
        work = await session.get(Work, work_id)
        assert work.status == "draft"


async def test_teacher_second_send_is_safe(seeded, tutor):
    tutor.teacher_ask = TeacherAsk(intent="work", topic="Дроби", goal="дроби", count=1)
    tutor.work_items = [(TaskDraft(prompt="1/4 + 1/4", answer="1/2"), True)]
    await post_update(seeded, message(900001, "Марина Сергеевна", "проверка", "t-3"))
    payload = button_payload(seeded, "Отправить классу")
    await post_update(seeded, callback(900001, "Марина Сергеевна", "cb-3a", payload))
    await post_update(seeded, callback(900001, "Марина Сергеевна", "cb-3b", payload))
    last = seeded.memory.sent[-1]["text"]
    assert "уже опубликована" in last or "Уже обработано" in last or "Отправил" in last


async def test_material_generation_refuses_without_fragments(seeded, tutor):
    factory = seeded.app.state.session_factory
    async with factory() as session:
        composed = await compose_draft(
            session,
            tutor,
            class_id=None,
            topic="Дроби",
            goal="сложение",
            count=2,
            difficulty="normal",
            audience="class",
            students=[],
            use_material=True,
        )
    assert composed.draft is None
    assert composed.error == MATERIAL_MISSING
    assert tutor.draft_calls == []


async def test_material_chunks_feed_the_prompt(seeded, tutor):
    factory = seeded.app.state.session_factory
    async with factory() as session:
        from app.db.models import SchoolClass

        class_id = await session.scalar(select(SchoolClass.id))
        text = "Сложение дробей. " + "Чтобы сложить дроби с разными знаменателями, приведи их к общему знаменателю. " * 8
        await save_material(
            session, class_id=class_id, author_id=1, title="§ Дроби", kind="text", text=text
        )
        await session.commit()
        fragments = await find_fragments(session, class_id, "сложение дробей", limit=2)
        assert fragments
        materials = await session.scalar(select(func.count()).select_from(Material))
        assert materials == 1


def test_loads_object_variants():
    assert loads_object('{"a": 1}') == {"a": 1}
    assert loads_object('```json\n{"a": 2}\n```') == {"a": 2}
    assert loads_object('вот ответ: {"a": 3} конец') == {"a": 3}
    assert loads_object("не json") is None
    assert loads_object('[1, 2]') is None
    assert loads_object(None) is None


def test_leaks_detects_result_markers():
    assert leaks("Складываем и получаем ответ: 5", "5")
    assert leaks("x = 12", "12")
    assert not leaks("Здесь 5 яблок", "5")
    assert not leaks("Ответ: 5", "7")
    assert not leaks("", "5")


def test_match_students_only_class_roster():
    roster = [(1, "Алексей Иванов"), (2, "Аня Петрова"), (3, "Анна Сидорова")]
    ids, found, unknown = match_students(["Алексей Иванов"], roster)
    assert ids == [1] and found == ["Алексей Иванов"] and unknown == []
    ids, found, unknown = match_students(["Марья"], roster)
    assert ids == [] and unknown == ["Марья"]
