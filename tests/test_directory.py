from tests.support import button_payload, callback, message, post_update
from tests.test_accounts import _consent, _started


async def test_student_applies_to_school_16_and_waits(seeded):
    api = seeded
    await post_update(api, _started(61616, "Оля"))
    await post_update(api, _consent(61616, "Оля"))
    assert "кто ты" in api.memory.sent[-1]["text"].casefold()
    await post_update(api, callback(61616, "Оля", "role-olya", button_payload(api, "Я ученик")))
    await post_update(api, callback(61616, "Оля", "city-olya", button_payload(api, "Благовещенск")))
    await post_update(
        api,
        callback(61616, "Оля", "school-olya", button_payload(api, "МАОУ Школа 16 гор. Благовещенск")),
    )
    assert "заявк" in api.memory.sent[-1]["text"].casefold()


async def test_start_command_ignores_case_and_whoami_is_open_outside_prod(seeded):
    api = seeded
    await post_update(api, message(900002, "Алексей", "/WHOAMI", "who-upper"))
    assert api.memory.sent[-1]["text"] == "user_id: 900002"
    await post_update(api, message(900002, "Алексей", "/START", "start-upper"))
    assert "кабинет" not in api.memory.sent[-1]["text"].casefold()


async def test_admin_seat_can_approve_a_teacher(seeded):
    api = seeded
    await post_update(api, _started(71717, "Ирина"))
    await post_update(api, _consent(71717, "Ирина"))
    await post_update(api, callback(71717, "Ирина", "role-i", button_payload(api, "Я учитель")))
    await post_update(api, callback(71717, "Ирина", "city-i", button_payload(api, "Благовещенск")))
    await post_update(
        api,
        callback(71717, "Ирина", "school-i", button_payload(api, "МАОУ Школа 16 гор. Благовещенск")),
    )
    await post_update(api, callback(71717, "Ирина", "seat-i", button_payload(api, "Администратор школы")))
    assert "администратор" in api.memory.sent[-1]["text"].casefold()

    await post_update(api, _started(81818, "Пётр"))
    await post_update(api, _consent(81818, "Пётр"))
    await post_update(api, callback(81818, "Пётр", "role-p", button_payload(api, "Я учитель")))
    await post_update(api, callback(81818, "Пётр", "city-p", button_payload(api, "Благовещенск")))
    await post_update(
        api,
        callback(81818, "Пётр", "school-p", button_payload(api, "МАОУ Школа 16 гор. Благовещенск")),
    )
    await post_update(api, callback(81818, "Пётр", "seat-p", button_payload(api, "Математика")))
    assert "заявк" in api.memory.sent[-1]["text"].casefold()

    await post_update(api, message(71717, "Ирина", "заявки", "apps-i"))
    await post_update(api, callback(71717, "Ирина", "ok-p", button_payload(api, "Принять Пётр")))
    assert "принял" in api.memory.sent[-1]["text"].casefold()
