import random
from fractions import Fraction

from app.domain.curriculum import TOPICS
from app.domain.tasks import TEMPLATES, generate_task
from app.domain.training import Action, StudentText, TrainState, reduce_turn


def test_each_topic_has_six_templates_and_new_variants():
    assert set(TEMPLATES) == {item.title for item in TOPICS}
    for title, builders in TEMPLATES.items():
        assert len(builders) >= 6
        for level in ("easy", "hard"):
            rng = random.Random(1)
            prompts = [generate_task(title, level, rng).prompt for _ in range(40)]
            assert len(set(prompts)) > 2
            sample = generate_task(title, level, random.Random(2))
            Fraction(sample.answer)


def test_two_correct_raises_the_level_and_two_wrong_lowers_it():
    rng = random.Random(3)
    state = reduce_turn(TrainState(), StudentText("дроби"), rng).state
    for _ in range(2):
        opened = reduce_turn(state, Action("to_practice"), rng)
        state = reduce_turn(opened.state, StudentText(opened.state.pending_answer or ""), rng).state
    assert state.level == "hard"
    state.level = "hard"
    state.correct_streak = 0
    state.wrong_streak = 0
    for _ in range(2):
        opened = reduce_turn(state, Action("again"), rng)
        state = reduce_turn(opened.state, StudentText("нет"), rng).state
    assert state.level == "easy"


def test_again_is_not_the_same_fixed_pair():
    rng = random.Random(4)
    state = reduce_turn(TrainState(), StudentText("геометрия"), rng).state
    prompts = []
    for _ in range(8):
        opened = reduce_turn(state, Action("to_practice"), rng)
        prompts.append(opened.state.pending_prompt)
        state = reduce_turn(opened.state, StudentText("нет"), rng).state
    assert len(set(prompts)) > 2
