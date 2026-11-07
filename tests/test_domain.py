from datetime import UTC, date, datetime, timedelta

from app.domain.answers import answers_match
from app.domain.curriculum import detect_topic
from app.domain.drafts import build_check_draft, build_stimul_draft
from app.domain.messages_ru import LINES
from app.domain.progress import TopicProgress, choose_next, streak
from app.domain.report import StateFact, TopicColumn, activity_line, build_report
from app.domain.status import Mark, TopicStatus, decide_status, mark_of
from app.domain.training import (
    Action,
    PhotoOnly,
    Start,
    StudentText,
    TrainState,
    present_state,
    present_turn,
    reduce_turn,
)
from app.llm.explainer import mistake_prompt, topic_prompt


def test_numeric_reference_accepts_fraction_and_decimal():
    assert answers_match("1/2", "0,5")
    assert answers_match("5", "x = 5")
    assert not answers_match("5", "4")
    assert not answers_match("5", "")


def _window(score: float, *, spaced: bool = True, last_two_wrong: bool = False) -> list[Mark]:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    marks: list[Mark] = []
    for index in range(10):
        correct = score > 0 and not (last_two_wrong and index >= 8)
        moment = start + timedelta(hours=13 * index) if spaced else start
        prompt = f"v{index}" if spaced else "same"
        marks.append(Mark(score, correct, prompt, moment))
    if last_two_wrong:
        # Средняя доля задаётся явно: восемь единиц и два нуля дают 0,8.
        marks = [Mark(1, True, f"v{index}", start + timedelta(hours=13 * index)) for index in range(8)]
        marks.append(Mark(0, False, "tail-a", start + timedelta(hours=13 * 8)))
        marks.append(Mark(0, False, "tail-b", start + timedelta(hours=13 * 9)))
    return marks


def test_status_boundaries_at_49_50_79_80_percent():
    assert decide_status([]) is None
    assert decide_status([mark_of(True, prompt="a")]) is TopicStatus.started
    assert decide_status([mark_of(False), mark_of(True)]) is TopicStatus.started
    assert decide_status(_window(0.49)) is TopicStatus.repeat
    assert decide_status(_window(0.50)) is TopicStatus.needs_practice
    assert decide_status(_window(0.79)) is TopicStatus.needs_practice
    assert decide_status(_window(0.80)) is TopicStatus.mastered
    assert decide_status(_window(0.80, spaced=False)) is TopicStatus.needs_practice
    assert decide_status(_window(0.80, last_two_wrong=True)) is TopicStatus.repeat


def test_hinted_correct_counts_as_half_and_only_the_last_ten_matter():
    start = datetime(2026, 10, 1, tzinfo=UTC)

    def series(hinted: bool) -> list[Mark]:
        marks = [mark_of(False, prompt=f"w{i}", at=start) for i in range(5)]
        marks.extend(mark_of(True, prompt=f"c{i}", at=start) for i in range(4))
        marks.append(mark_of(True, hinted=hinted, prompt="edge", at=start))
        return marks

    assert decide_status(series(True)) is TopicStatus.repeat
    assert decide_status(series(False)) is TopicStatus.needs_practice
    old = [mark_of(False, prompt=f"old{i}", at=start) for i in range(10)]
    fresh = [
        mark_of(True, prompt=f"new{i}", at=start + timedelta(hours=13 * (i + 1)))
        for i in range(10)
    ]
    assert decide_status(old + fresh) is TopicStatus.mastered


def test_streak_counts_consecutive_practice_days():
    today = date(2026, 10, 27)
    assert streak({today, today - timedelta(days=1), today - timedelta(days=2)}, today) == 3
    assert streak({today - timedelta(days=1)}, today) == 1
    assert streak({today - timedelta(days=2)}, today) == 0
    assert streak({today, today - timedelta(days=2)}, today) == 1


def test_square_context_separates_geometry_from_equations():
    assert detect_topic("площадь квадрата") == "Геометрия"
    assert detect_topic("ПЛОЩАДЬ КВАДРАТА") == "Геометрия"
    assert detect_topic("сторона квадрата") == "Геометрия"
    assert detect_topic("квадратное уравнение") == "Квадратные уравнения и дискриминант"
    assert detect_topic("Квадратное уравнение") == "Квадратные уравнения и дискриминант"
    assert detect_topic("квадрат") is None
    turn = reduce_turn(TrainState(), StudentText("квадрат"))
    assert turn.replies[0].text == "Это про геометрию?"
    labels = [button.text for button in turn.replies[0].buttons]
    assert labels == ["Да, геометрия", "Нет, уравнение"]
    geometry = reduce_turn(turn.state, Action("pick", "Геометрия"))
    assert geometry.state.topic_title == "Геометрия"


def test_reply_sets_have_several_variants_and_keep_the_tone():
    banned = ("я стимул", "приём", "эталон", "конечно!", "отличный вопрос", "как ии")
    for key, options in LINES.items():
        assert 3 <= len(options) <= 5, key
        assert len(set(options)) == len(options)
        blob = " ".join(options).casefold()
        for word in banned:
            assert word not in blob, key


def test_start_closes_an_open_answer():
    state = TrainState(
        mode="submission",
        step="check",
        pending_answer="4",
        pending_prompt="2+2",
    )
    turn = reduce_turn(state, Start())
    assert turn.state.mode == "training"
    assert turn.state.step == "done"
    assert turn.state.pending_answer is None
    follow = reduce_turn(turn.state, StudentText("не понимаю дроби"))
    assert follow.attempt is None
    assert follow.state.step == "explain"


def test_greeting_has_variants_and_does_not_introduce_itself():
    first = reduce_turn(TrainState(), Start())
    second = reduce_turn(first.state, Start())
    assert first.replies[0].text != second.replies[0].text
    blob = first.replies[0].text.casefold()
    assert "стимул" not in blob
    assert "приём" not in blob
    assert "эталон" not in blob
    assert "готовый ответ" not in blob


def test_question_is_not_solved():
    turn = reduce_turn(TrainState(), StudentText("Как решить уравнение 17+4"))
    assert "21" not in turn.replies[0].text
    assert "17+4" not in turn.replies[0].text
    assert "Пример." in turn.replies[0].text
    assert detect_topic("квадратные уравнения") == "Квадратные уравнения и дискриминант"


def test_wrong_practice_feedback_omits_the_reference():
    opened = reduce_turn(TrainState(), StudentText("линейные уравнения"), __import__("random").Random(1))
    practiced = reduce_turn(opened.state, Action("to_practice"), __import__("random").Random(1))
    graded = reduce_turn(practiced.state, StudentText("нет"))
    assert graded.attempt is not None
    assert graded.attempt.correct is False
    assert graded.attempt.expected
    assert graded.attempt.expected not in graded.replies[0].text


def test_public_view_hides_the_reference():
    numbers = __import__("random").Random(1)
    opened = reduce_turn(TrainState(), StudentText("линейные уравнения"), numbers)
    practiced = reduce_turn(opened.state, Action("to_practice"), numbers)
    graded = reduce_turn(practiced.state, StudentText("нет"), numbers)
    view = present_turn(graded)
    assert view["correct"] is False
    assert graded.state.step == "check"
    assert graded.attempt.expected not in (view["feedback"] or "")
    assert "pending_answer" not in view
    assert "reference" not in view
    snapshot = present_state(
        reduce_turn(opened.state, Action("to_practice"), __import__("random").Random(1)).state
    )
    assert snapshot["awaiting_answer"] is True
    assert snapshot["task"]
    assert snapshot["feedback"] is None


def test_task_text_survives_wrong_answer_and_hints():
    numbers = __import__("random").Random(3)
    opened = reduce_turn(TrainState(), StudentText("дроби"), numbers)
    practiced = reduce_turn(opened.state, Action("to_practice"), numbers)
    prompt = practiced.state.pending_prompt
    assert present_turn(practiced)["task"] == prompt
    wrong = reduce_turn(practiced.state, StudentText("999"), numbers)
    wrong_view = present_turn(wrong)
    assert wrong_view["task"] == prompt
    assert wrong_view["feedback"]
    assert wrong_view["awaiting_answer"] is True
    hinted = reduce_turn(wrong.state, Action("hint"), numbers)
    hint_view = present_turn(hinted)
    assert hint_view["task"] == prompt
    assert hint_view["hint"] and hint_view["hint"] != prompt
    assert hint_view["feedback"] is None
    step = reduce_turn(hinted.state, Action("hint"), numbers)
    assert present_turn(step)["task"] == prompt
    unsure = reduce_turn(step.state, StudentText("не знаю"), numbers)
    assert present_turn(unsure)["task"] == prompt
    stale = reduce_turn(step.state, Action("hint", version=0), numbers)
    assert present_turn(stale)["task"] == prompt
    snapshot = present_state(step.state)
    assert snapshot["task"] == prompt
    assert snapshot["hint"]
    for view in (wrong_view, hint_view, snapshot):
        assert "pending_answer" not in view
        assert "expected" not in view


def test_practice_skips_prompts_the_student_already_solved():
    from random import Random

    from app.domain.tasks import generate_task

    first = generate_task("Дроби", "easy", Random(5))
    again = generate_task("Дроби", "easy", Random(5), {first.prompt})
    assert again.prompt != first.prompt
    pool = {generate_task("Геометрия", "easy", Random(seed)).prompt for seed in range(400)}
    fallback = generate_task("Геометрия", "easy", Random(1), pool)
    assert fallback.prompt and fallback.answer

    opened = reduce_turn(TrainState(), StudentText("дроби"), Random(7))
    plain = reduce_turn(opened.state, Action("to_practice"), Random(7))
    seen = TrainState(**{**opened.state.__dict__, "seen_prompts": [plain.state.pending_prompt]})
    fresh = reduce_turn(seen, Action("to_practice"), Random(7))
    assert fresh.state.pending_prompt != plain.state.pending_prompt
    graded = reduce_turn(fresh.state, StudentText("0"), Random(7))
    assert fresh.state.pending_prompt in graded.state.seen_prompts
    other = reduce_turn(graded.state, Action("pick", "Геометрия"))
    assert other.state.seen_prompts == []


def test_stimul_draft_has_no_duplicate_prompts():
    draft = build_stimul_draft("Дроби", "Проверить", 12, "normal", "class", [])
    prompts = [item["prompt"] for item in draft["items"]]
    assert len(set(prompts)) == len(prompts)


def test_check_draft_comes_from_the_bank_and_is_not_stored():
    draft = build_check_draft("Дроби", "Проверить общий знаменатель", 4, "normal", "class", [])
    assert draft is not None
    assert draft["persisted"] is False
    assert draft["source"] == "bank"
    assert draft["items"][0]["reference"] == "1/2"
    assert draft["note"]
    assert build_check_draft("История", "Цель", 1, "easy", "class", []) is None


def test_stimul_draft_follows_a_known_family_and_refuses_the_rest():
    draft = build_stimul_draft(
        "Дроби с разными знаменателями",
        "Проверить сложение",
        2,
        "normal",
        "class",
        ["Аня"],
    )
    assert draft is not None
    assert draft["topic"] == "Дроби с разными знаменателями"
    assert len(draft["items"]) == 2
    assert draft["items"][0]["reference"]
    assert "8 класса" in draft["note"]
    assert build_stimul_draft("История Древнего мира", "Даты", 1, "easy", "class", []) is None


def test_activity_line_names_the_topic_and_not_the_answer():
    assert activity_line(mode="training", step="practice", title="Дроби", open_work=None) == "Сейчас разбирает «Дроби»"
    assert activity_line(mode=None, step=None, title=None, open_work="Проценты") == "Не сдал «Проценты»"
    assert "1/2" not in activity_line(mode="training", step="check", title="Дроби", open_work=None)


def test_submission_does_not_solve_a_page():
    turn = reduce_turn(TrainState(mode="submission"), PhotoOnly())
    assert "задание" in turn.replies[0].text.casefold()
    assert "21" not in turn.replies[0].text


def test_next_step_uses_the_weakest_topic_with_attempts():
    empty = choose_next(
        [
            TopicProgress("Дроби", 1, None, None),
            TopicProgress("Геометрия", 2, None, None),
        ]
    )
    assert empty is not None
    assert empty.topic_title == "Дроби"
    tied = choose_next(
        [
            TopicProgress("Геометрия", 2, TopicStatus.needs_practice, 50, attempts=4, rank_score=0.5),
            TopicProgress("Дроби", 1, TopicStatus.needs_practice, 50, attempts=4, rank_score=0.5),
        ]
    )
    assert tied is not None
    assert tied.topic_title == "Дроби"


def test_next_step_picks_the_weakest_topic():
    step = choose_next(
        [
            TopicProgress("Дроби", 1, TopicStatus.needs_practice, 70),
            TopicProgress("Геометрия", 2, TopicStatus.repeat, 30),
            TopicProgress("Линейные уравнения", 3, TopicStatus.mastered, 100),
        ]
    )
    assert step is not None
    assert step.topic_title == "Геометрия"
    assert step.label == "Повторить тему «Геометрия»"


def test_class_report_has_three_statuses_and_no_chat_text():
    today = date(2026, 10, 27)
    report = build_report(
        "8Б",
        [
            TopicColumn("Дроби", 1),
            TopicColumn("Геометрия", 2),
            TopicColumn("Линейные уравнения", 3),
        ],
        ["Алексей", "Аня", "Ольга"],
        {
            ("Алексей", "Геометрия"): StateFact(TopicStatus.repeat, 0, today - timedelta(days=9)),
            ("Аня", "Дроби"): StateFact(TopicStatus.mastered, 100, today),
            ("Ольга", "Линейные уравнения"): StateFact(TopicStatus.needs_practice, 100, today),
        },
        {"Геометрия": 2},
        today,
    )
    payload = report.as_dict()
    blob = str(payload)
    assert "mastered" in blob
    assert "needs_practice" in blob
    assert "repeat" in blob
    assert "17+4" not in blob
    assert "СЕКРЕТ" not in blob
    assert payload["frequent_mistakes"] == "Чаще всего ошибки в теме «Геометрия»."
    assert payload["stalled"]


def test_prompts_do_not_ask_for_the_students_numbers():
    assert "17+4" not in topic_prompt("Дроби")
    assert "5" not in mistake_prompt("Линейные уравнения", "Раздели обе части на число перед x.")
