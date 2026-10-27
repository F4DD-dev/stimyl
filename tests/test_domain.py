from datetime import date, timedelta

from app.domain.answers import answers_match
from app.domain.curriculum import detect_topic
from app.domain.progress import TopicProgress, choose_next, streak
from app.domain.report import StateFact, TopicColumn, build_report
from app.domain.status import TopicStatus, decide_status
from app.domain.training import Action, PhotoOnly, StudentText, TrainState, reduce_turn
from app.llm.explainer import mistake_prompt, topic_prompt


def test_numeric_reference_accepts_fraction_and_decimal():
    assert answers_match("1/2", "0,5")
    assert answers_match("5", "x = 5")
    assert not answers_match("5", "4")
    assert not answers_match("5", "")


def test_status_thresholds_cover_three_states():
    assert decide_status([]) is None
    assert decide_status([True]) is TopicStatus.needs_practice
    assert decide_status([False]) is TopicStatus.repeat
    assert decide_status([True, True]) is TopicStatus.mastered
    assert decide_status([True, False]) is TopicStatus.needs_practice
    assert decide_status([True, True, False, False]) is TopicStatus.repeat
    assert decide_status([True] * 8 + [False, False]) is TopicStatus.repeat
    assert decide_status([True] * 4 + [False]) is TopicStatus.mastered


def test_streak_counts_consecutive_practice_days():
    today = date(2026, 10, 27)
    assert streak({today, today - timedelta(days=1), today - timedelta(days=2)}, today) == 3
    assert streak({today - timedelta(days=1)}, today) == 1
    assert streak({today - timedelta(days=2)}, today) == 0
    assert streak({today, today - timedelta(days=2)}, today) == 1


def test_question_is_not_solved():
    turn = reduce_turn(TrainState(), StudentText("Как решить уравнение 17+4"))
    assert "21" not in turn.replies[0].text
    assert "17+4" not in turn.replies[0].text
    assert "Пример." in turn.replies[0].text
    assert detect_topic("квадратные уравнения") == "Квадратные уравнения и дискриминант"


def test_wrong_practice_feedback_omits_the_reference():
    opened = reduce_turn(TrainState(), StudentText("линейные уравнения"))
    practiced = reduce_turn(opened.state, Action("to_practice"))
    graded = reduce_turn(practiced.state, StudentText("нет"))
    assert graded.attempt is not None
    assert graded.attempt.correct is False
    assert graded.attempt.expected == "5"
    assert "5" not in graded.replies[0].text


def test_submission_does_not_solve_a_page():
    turn = reduce_turn(TrainState(mode="submission"), PhotoOnly())
    assert "не решаю" in turn.replies[0].text
    assert "21" not in turn.replies[0].text


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
