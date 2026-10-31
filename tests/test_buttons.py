import random

from sqlalchemy import func, select

from app.db.models import Attempt
from app.domain.training import Action, StudentText, TrainState, reduce_turn
from tests.support import button_payload, callback, message, post_update


def test_stale_button_does_not_open_a_second_task():
    rng = random.Random(1)
    asked = reduce_turn(TrainState(), StudentText("дроби"), rng)
    opened = reduce_turn(asked.state, Action("to_practice", version=asked.state.version), rng)
    again = reduce_turn(opened.state, Action("to_practice", version=asked.state.version), rng)
    assert "неактуальна" in again.replies[0].text
    assert again.attempt is None
    assert again.state.task_index == opened.state.task_index
    assert again.state.pending_prompt == opened.state.pending_prompt
    assert again.state.version == opened.state.version


async def test_double_tap_does_not_create_a_second_task(seeded):
    api = seeded
    await post_update(api, message(900002, "Алексей", "Объясни дроби", "dbl-q"))
    payload = button_payload(api, "К практике")
    assert payload.startswith("v")
    await post_update(api, callback(900002, "Алексей", "dbl-1", payload))
    await post_update(api, callback(900002, "Алексей", "dbl-2", payload))
    assert "неактуальна" in api.memory.sent[-1]["text"]
    factory = api.app.state.session_factory
    async with factory() as session:
        count = await session.scalar(select(func.count()).select_from(Attempt))
    assert count == 0


def test_current_button_still_works_once():
    rng = random.Random(2)
    asked = reduce_turn(TrainState(), StudentText("геометрия"), rng)
    opened = reduce_turn(asked.state, Action("to_practice", version=asked.state.version), rng)
    assert opened.state.step == "check"
    assert opened.state.version == asked.state.version + 1
