from tests.support import message, post_update
from tests.test_accounts import _consent, _started


async def test_new_person_is_asked_for_a_phone_button(seeded):
    api = seeded
    await post_update(api, _started(61616, "Оля"))
    await post_update(api, _consent(61616, "Оля"))
    buttons = api.memory.sent[-1]["buttons"]
    assert any(button.get("type") == "request_contact" for button in buttons)
    assert "кто ты" not in api.memory.sent[-1]["text"].casefold()


async def test_start_command_ignores_case_and_whoami_is_open_outside_prod(seeded):
    api = seeded
    await post_update(api, message(900002, "Алексей", "/WHOAMI", "who-upper"))
    assert api.memory.sent[-1]["text"] == "user_id: 900002"
    await post_update(api, message(900002, "Алексей", "/START", "start-upper"))
    assert "кабинет" not in api.memory.sent[-1]["text"].casefold()
