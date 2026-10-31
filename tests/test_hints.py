import random

from app.domain.training import Action, StudentText, TrainState, reduce_turn


def _open(rng: random.Random):
    state = reduce_turn(TrainState(), StudentText("дроби"), rng).state
    return reduce_turn(state, Action("to_practice"), rng)


def test_task_offers_hint_skip_and_another_topic():
    opened = _open(random.Random(1))
    labels = [button.text for button in opened.replies[0].buttons]
    assert labels == ["Подсказка", "Пропустить", "Другая тема"]


def test_i_dont_know_is_a_hint_not_an_attempt():
    rng = random.Random(2)
    opened = _open(rng)
    answer = opened.state.pending_answer
    hinted = reduce_turn(opened.state, StudentText("не знаю"), rng)
    assert hinted.attempt is None
    assert hinted.state.pending_answer == answer
    assert hinted.state.hint_step == 1
    assert hinted.state.task_misses == 0
    again = reduce_turn(hinted.state, StudentText("?"), rng)
    assert again.state.hint_step == 2
    assert again.replies[0].text != hinted.replies[0].text


def test_third_wrong_shows_a_similar_example_and_a_new_task():
    rng = random.Random(3)
    opened = _open(rng)
    first_prompt = opened.state.pending_prompt
    state = opened.state
    turn = None
    for _ in range(3):
        turn = reduce_turn(state, StudentText("нет"), rng)
        state = turn.state
    assert turn is not None
    assert turn.attempt is not None
    assert turn.attempt.correct is False
    blob = " ".join(reply.text for reply in turn.replies)
    assert "Похожий пример." in blob
    assert state.pending_prompt != first_prompt
    assert state.step == "check"


def test_a_new_question_is_not_graded_as_an_answer():
    rng = random.Random(4)
    opened = _open(rng)
    asked = reduce_turn(opened.state, StudentText("как решить квадратное уравнение"), rng)
    assert asked.attempt is None
    assert asked.replies[0].text == "Это ответ или новый вопрос?"
    switched = reduce_turn(asked.state, Action("as_question"), rng)
    assert switched.state.topic_title == "Квадратные уравнения и дискриминант"
    assert switched.attempt is None


def test_skip_gives_another_variant_without_an_attempt():
    rng = random.Random(5)
    opened = _open(rng)
    skipped = reduce_turn(opened.state, Action("skip"), rng)
    assert skipped.attempt is None
    assert skipped.state.pending_prompt != opened.state.pending_prompt
