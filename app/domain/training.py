import random
from dataclasses import asdict, dataclass, field

from app.domain.answers import answers_match, is_attempt, parse_answer
from app.domain.curriculum import TOPICS, TopicMaterial, classify_topic, topic_by_title
from app.domain.messages_ru import (
    BTN_AGAIN,
    BTN_ANSWER,
    BTN_GEOMETRY_NO,
    BTN_GEOMETRY_YES,
    BTN_HINT,
    BTN_MORE_EXAMPLE,
    BTN_OTHER,
    BTN_PRACTICE,
    BTN_QUESTION,
    BTN_SKIP,
    EXAMPLE_MARK,
    STALE_MARK,
    TASK_MARK,
    say,
    similar_example,
)
from app.domain.tasks import GeneratedTask, generate_task


@dataclass
class ButtonSpec:
    text: str
    action: str
    topic_title: str | None = None


@dataclass
class Reply:
    lead: str
    body: str = ""
    buttons: tuple[ButtonSpec, ...] = ()
    replaceable_lead: bool = False
    topic_title: str | None = None
    kind: str = ""

    @property
    def text(self) -> str:
        if self.body:
            return f"{self.lead}\n\n{self.body}"
        return self.lead


@dataclass
class AttemptDraft:
    topic_title: str
    prompt: str
    expected: str
    answer: str
    correct: bool
    feedback: str
    hint: str
    hinted: bool = False


@dataclass
class TrainState:
    mode: str = "training"
    step: str = "done"
    topic_title: str | None = None
    example_index: int = 0
    task_index: int = 0
    level: str = "easy"
    correct_streak: int = 0
    wrong_streak: int = 0
    hint_step: int = 0
    task_misses: int = 0
    version: int = 1
    line_cursor: int = 0
    last_line: str = ""
    pending_answer: str | None = None
    pending_hint: str | None = None
    pending_step: str | None = None
    pending_prompt: str | None = None
    pending_text: str | None = None
    # Условия, которые ученик уже решал по текущей теме. Заполняет вызывающий код из attempts.
    seen_prompts: list[str] = field(default_factory=list)


SEEN_LIMIT = 200


def _remember_prompt(state: TrainState, prompt: str | None) -> None:
    if prompt and prompt not in state.seen_prompts:
        state.seen_prompts = [*state.seen_prompts, prompt][-SEEN_LIMIT:]


@dataclass
class Turn:
    state: TrainState
    replies: list[Reply]
    attempt: AttemptDraft | None = None


@dataclass
class Start:
    pass


@dataclass
class PhotoOnly:
    pass


@dataclass
class StudentText:
    text: str


@dataclass
class Action:
    name: str
    topic_title: str | None = None
    version: int | None = None


Event = Start | PhotoOnly | StudentText | Action


def reduce_turn(state: TrainState, event: Event, rng: random.Random | None = None) -> Turn:
    current = TrainState(**asdict(state))
    numbers = rng or random.Random()
    if isinstance(event, Start):
        current.mode = "training"
        current.step = "done"
        current.pending_answer = None
        current.pending_hint = None
        current.pending_step = None
        current.pending_prompt = None
        current.pending_text = None
        return Turn(current, [Reply(say(current, "greeting"))])
    if isinstance(event, PhotoOnly):
        if current.mode == "submission":
            return Turn(current, [Reply(say(current, "submission_photo"))])
        return Turn(current, [Reply(say(current, "training_photo"))])
    if isinstance(event, Action):
        if event.version is not None and event.version != current.version:
            return Turn(
                current,
                [Reply(say(current, "stale_button"))],
            )
        turn = _on_action(current, event, numbers)
        turn.state.version += 1
        return turn
    if current.mode == "submission" and current.step != "check":
        return Turn(current, [Reply(say(current, "submission_text"))])
    if current.step == "check" and current.pending_answer:
        turn = _grade(current, event.text, numbers)
    else:
        turn = _ask(current, event.text)
    turn.state.version += 1
    return turn


def _ask(state: TrainState, text: str) -> Turn:
    guess = classify_topic(text)
    if guess.ask_geometry:
        return Turn(
            state,
            [
                Reply(
                    say(state, "ask_geometry"),
                    buttons=(
                        ButtonSpec(BTN_GEOMETRY_YES, "pick", TOPICS[3].title),
                        ButtonSpec(BTN_GEOMETRY_NO, "pick", TOPICS[2].title),
                    ),
                )
            ],
        )
    if not guess.confident or guess.title is None:
        buttons = tuple(ButtonSpec(item.title, "pick", item.title) for item in TOPICS)
        return Turn(state, [Reply(say(state, "unknown_topic"), buttons=buttons)])
    return _open_topic(state, guess.title)


def _on_action(state: TrainState, event: Action, rng: random.Random) -> Turn:
    if event.name in {"pick", "review"} and event.topic_title:
        return _open_topic(state, event.topic_title)
    material = topic_by_title(state.topic_title or "")
    if material is None:
        buttons = tuple(ButtonSpec(item.title, "pick", item.title) for item in TOPICS)
        return Turn(state, [Reply(say(state, "unknown_topic"), buttons=buttons)])
    if event.name == "more_example":
        state.example_index += 1
        state.step = "explain"
        return Turn(state, [_explain_reply(material, state.example_index)])
    if event.name in {"to_practice", "again", "skip"}:
        return _practice(state, material, rng)
    if event.name == "hint":
        return _hint(state)
    if event.name == "other":
        return _other_topic(state)
    if event.name == "as_answer":
        text = state.pending_text or ""
        state.pending_text = None
        if not text:
            return Turn(state, [Reply(say(state, "write_answer"), buttons=_task_buttons())])
        return _grade(state, text, rng, force=True)
    if event.name == "as_question":
        text = state.pending_text or ""
        state.pending_text = None
        _clear_task(state)
        return _ask(state, text)
    return Turn(state, [Reply(say(state, "ask_next"))])


def _open_topic(state: TrainState, title: str) -> Turn:
    material = topic_by_title(title)
    if material is None:
        return Turn(state, [Reply(say(state, "unknown_topic"))])
    if state.topic_title != material.title:
        state.seen_prompts = []
    state.topic_title = material.title
    state.step = "explain"
    state.example_index = 0
    state.task_index = 0
    state.level = "easy"
    state.correct_streak = 0
    state.wrong_streak = 0
    state.hint_step = 0
    state.task_misses = 0
    state.pending_answer = None
    state.pending_hint = None
    state.pending_step = None
    state.pending_prompt = None
    state.pending_text = None
    return Turn(state, [_explain_reply(material, 0)])


def _reset_topic(state: TrainState, title: str) -> None:
    state.mode = "training"
    if state.topic_title != title:
        state.seen_prompts = []
    state.topic_title = title
    state.example_index = 0
    state.task_index = 0
    state.correct_streak = 0
    state.wrong_streak = 0
    state.hint_step = 0
    state.task_misses = 0
    state.pending_text = None
    _clear_task(state)


def _open_task(state: TrainState, task: GeneratedTask) -> Reply:
    state.step = "check"
    state.task_index += 1
    state.hint_step = 0
    state.task_misses = 0
    state.pending_answer = task.answer
    state.pending_hint = task.hint or None
    state.pending_step = task.first_step or None
    state.pending_prompt = task.prompt
    state.pending_text = None
    return Reply(f"{TASK_MARK} {task.prompt}", buttons=_task_buttons())


def guided_lesson(
    state: TrainState,
    title: str,
    explanation: str,
    example: str,
    task: GeneratedTask | None,
) -> Turn:
    """Разбор вопроса ученика: объяснение и пример от модели, задание с эталоном, который принял код."""
    current = TrainState(**asdict(state))
    _reset_topic(current, title)
    lead = explanation or (topic_by_title(title).explanation if topic_by_title(title) else "")
    body = f"{EXAMPLE_MARK} {example}" if example else ""
    if task is None:
        current.step = "explain"
        buttons = (ButtonSpec(BTN_PRACTICE, "to_practice"),)
        if topic_by_title(title) is not None:
            buttons = (ButtonSpec(BTN_MORE_EXAMPLE, "more_example"), *buttons)
        current.version += 1
        return Turn(current, [Reply(lead, body, buttons=buttons, topic_title=title)])
    first = Reply(lead, body, topic_title=title)
    second = _open_task(current, task)
    current.version += 1
    return Turn(current, [first, second])


def guided_task(state: TrainState, task: GeneratedTask) -> Turn:
    current = TrainState(**asdict(state))
    reply = _open_task(current, task)
    current.version += 1
    return Turn(current, [reply])


def guided_direct(state: TrainState, text: str) -> Turn:
    """Прямой ответ на вопрос ученика: обычная реплика без урока и кнопок."""
    current = TrainState(**asdict(state))
    current.version += 1
    return Turn(current, [Reply(text)])


def guided_notice(state: TrainState, key: str, *, topics: bool = False) -> Turn:
    current = TrainState(**asdict(state))
    buttons = tuple(ButtonSpec(item.title, "pick", item.title) for item in TOPICS) if topics else ()
    reply = Reply(say(current, key), buttons=buttons)
    current.version += 1
    return Turn(current, [reply])


def _explain_reply(material: TopicMaterial, example_index: int) -> Reply:
    example = material.examples[example_index % len(material.examples)]
    return Reply(
        lead=material.explanation,
        body=f"{EXAMPLE_MARK} {example.text}",
        buttons=(
            ButtonSpec(BTN_MORE_EXAMPLE, "more_example"),
            ButtonSpec(BTN_PRACTICE, "to_practice"),
        ),
        replaceable_lead=True,
        topic_title=material.title,
    )


def _task_buttons() -> tuple[ButtonSpec, ...]:
    return (
        ButtonSpec(BTN_HINT, "hint"),
        ButtonSpec(BTN_SKIP, "skip"),
        ButtonSpec(BTN_OTHER, "other"),
    )


def _practice(state: TrainState, material: TopicMaterial, rng: random.Random) -> Turn:
    task = generate_task(material.title, state.level, rng, set(state.seen_prompts))
    state.step = "check"
    state.task_index += 1
    state.hint_step = 0
    state.task_misses = 0
    state.pending_answer = task.answer
    state.pending_hint = task.hint
    state.pending_step = task.first_step
    state.pending_prompt = task.prompt
    state.pending_text = None
    return Turn(state, [Reply(f"{TASK_MARK} {task.prompt}", buttons=_task_buttons())])


def _hint(state: TrainState) -> Turn:
    if state.hint_step < 1:
        state.hint_step = 1
        text = state.pending_hint or say(state, "hint_fallback")
    else:
        state.hint_step = 2
        text = state.pending_step or say(state, "step_fallback")
    return Turn(state, [Reply(text, buttons=_task_buttons(), kind="hint")])


def _other_topic(state: TrainState) -> Turn:
    _clear_task(state)
    buttons = tuple(ButtonSpec(item.title, "pick", item.title) for item in TOPICS)
    return Turn(state, [Reply(say(state, "other_topic"), buttons=buttons)])


def _clear_task(state: TrainState) -> None:
    state.step = "done"
    state.hint_step = 0
    state.task_misses = 0
    state.pending_answer = None
    state.pending_hint = None
    state.pending_step = None
    state.pending_prompt = None


def _looks_like_question(text: str) -> bool:
    if parse_answer(text).values:
        return False
    if "?" in text or len(text.split()) >= 4:
        return True
    guess = classify_topic(text)
    return guess.confident or guess.ask_geometry


def _grade(state: TrainState, answer: str, rng: random.Random, force: bool = False) -> Turn:
    if not is_attempt(answer):
        return _hint(state)
    if not force and _looks_like_question(answer):
        state.pending_text = answer.strip()
        return Turn(
            state,
            [
                Reply(
                    say(state, "answer_or_question"),
                    buttons=(
                        ButtonSpec(BTN_ANSWER, "as_answer"),
                        ButtonSpec(BTN_QUESTION, "as_question"),
                    ),
                )
            ],
        )
    expected = state.pending_answer or ""
    correct = answers_match(expected, answer)
    hint = state.pending_hint or say(state, "hint_fallback")
    feedback = say(state, "correct") if correct else f"{say(state, 'wrong')} {hint}"
    if correct:
        state.correct_streak += 1
        state.wrong_streak = 0
        state.task_misses = 0
    else:
        state.wrong_streak += 1
        state.correct_streak = 0
        state.task_misses += 1
    if state.correct_streak >= 2:
        state.level = "hard"
    if state.wrong_streak >= 2:
        state.level = "easy"
    third = not correct and state.task_misses >= 3
    draft = AttemptDraft(
        topic_title=state.topic_title or "",
        prompt=state.pending_prompt or "",
        expected=expected,
        answer=answer.strip(),
        correct=correct,
        feedback=feedback,
        hint=hint,
        hinted=state.hint_step > 0,
    )
    _remember_prompt(state, state.pending_prompt)
    if third and topic_by_title(state.topic_title or "") is not None:
        return _third_miss(state, rng, draft)
    if not correct:
        return Turn(state, [Reply(feedback, buttons=_task_buttons())], attempt=draft)
    state.step = "done"
    state.pending_answer = None
    state.pending_hint = None
    state.pending_step = None
    state.pending_prompt = None
    state.pending_text = None
    return Turn(
        state,
        [Reply(feedback, buttons=(ButtonSpec(BTN_AGAIN, "again"),))],
        attempt=draft,
    )


def _third_miss(state: TrainState, rng: random.Random, draft: AttemptDraft) -> Turn:
    material = topic_by_title(state.topic_title or "")
    assert material is not None
    example = generate_task(material.title, state.level, rng, {*state.seen_prompts, draft.prompt})
    _remember_prompt(state, example.prompt)
    fresh = _practice(state, material, rng)
    shown = similar_example(state, example.prompt, example.answer)
    return Turn(state, [Reply(shown), *fresh.replies], attempt=draft)


def present_turn(turn: Turn, status_line: str | None = None) -> dict:
    """Lesson payload for the student. Never includes the reference answer.

    While a task is open, `task` is always its prompt: hints, feedback and notices
    go to their own fields and never replace the task text."""
    reply = turn.replies[-1] if turn.replies else None
    lead = reply.lead if reply else ""
    explanation = None
    example = None
    task = None
    feedback = None
    notice = None
    hint = None
    if STALE_MARK in lead:
        notice = lead
    elif turn.attempt is not None and not lead.startswith(TASK_MARK):
        feedback = lead or None
    elif reply is not None and (reply.replaceable_lead or reply.topic_title):
        explanation, example = _explain_parts(reply)
    elif lead.startswith(TASK_MARK):
        task = lead.split(TASK_MARK, 1)[1].strip() or None
    elif reply is not None and reply.kind == "hint":
        hint = lead or None
    else:
        notice = lead or None
    if turn.state.step == "check" and turn.state.pending_prompt:
        task = turn.state.pending_prompt
    elif task is None and turn.attempt is not None:
        task = turn.attempt.prompt or None
    earlier = next((item for item in turn.replies[:-1] if item.topic_title), None)
    if earlier is not None and explanation is None:
        explanation, example = _explain_parts(earlier)
    actions = [
        {"action": spec.action, "label": spec.text, "topic": spec.topic_title}
        for spec in (reply.buttons if reply else ())
    ]
    return {
        "ok": True,
        "mode": turn.state.mode,
        "step": turn.state.step,
        "topic": turn.state.topic_title,
        "explanation": explanation,
        "example": example,
        "task": task,
        "hint": hint,
        "feedback": feedback,
        "correct": None if turn.attempt is None else turn.attempt.correct,
        "given": None if turn.attempt is None else turn.attempt.answer,
        "actions": actions,
        "notice": notice,
        "status_line": status_line,
        "version": turn.state.version,
        "awaiting_answer": turn.state.step == "check" and bool(turn.state.pending_answer),
        "photo_received": False,
        "photo_note": None,
    }


def _explain_parts(reply: Reply) -> tuple[str | None, str | None]:
    body = reply.body
    if body.startswith(EXAMPLE_MARK):
        example = body.split(EXAMPLE_MARK, 1)[1].strip() or None
    else:
        example = body or None
    return reply.lead or None, example


def present_state(state: TrainState) -> dict:
    if state.mode == "submission" and state.step != "check":
        view = _blank_lesson(state)
        view["notice"] = say(state, "submission_notice")
        return view
    material = topic_by_title(state.topic_title or "")
    if state.step == "explain" and material is not None:
        clone = TrainState(**asdict(state))
        return present_turn(Turn(clone, [_explain_reply(material, clone.example_index)]))
    if state.step == "check" and state.pending_prompt:
        clone = TrainState(**asdict(state))
        view = present_turn(
            Turn(clone, [Reply(f"{TASK_MARK} {clone.pending_prompt}", buttons=_task_buttons())])
        )
        if clone.hint_step >= 2:
            view["hint"] = clone.pending_step
        elif clone.hint_step == 1:
            view["hint"] = clone.pending_hint
        return view
    return _blank_lesson(state)


def _blank_lesson(state: TrainState) -> dict:
    return {
        "ok": True,
        "mode": state.mode,
        "step": "idle",
        "topic": state.topic_title,
        "explanation": None,
        "example": None,
        "task": None,
        "hint": None,
        "feedback": None,
        "correct": None,
        "given": None,
        "actions": [],
        "notice": None,
        "status_line": None,
        "version": state.version,
        "awaiting_answer": False,
        "photo_received": False,
        "photo_note": None,
    }
