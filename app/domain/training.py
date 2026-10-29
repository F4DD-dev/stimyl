from dataclasses import asdict, dataclass

from app.domain.answers import answers_match
from app.domain.curriculum import TOPICS, TopicMaterial, detect_topic, topic_by_title

GREETING = (
    "Привет. Я Стимул. Пришли вопрос по математике 8 класса — "
    "объясню приём и дам практику. Готовый ответ к твоей задаче не пишу."
)
TRAINING_PHOTO = "Фото вижу. Напиши тему или вопрос словами. Страницу за ученика не решаю."
SUBMISSION_PHOTO = (
    "Это сдача работы. Пришли ответ на выданное задание. Страницу учебника я не решаю."
)
SUBMISSION_TEXT = "Жду ответ на выданное задание. Новую задачу со страницы не решаю."
UNKNOWN_TOPIC = "Выбери тему математики 8 класса."


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


@dataclass
class TrainState:
    mode: str = "training"
    step: str = "done"
    topic_title: str | None = None
    example_index: int = 0
    task_index: int = 0
    pending_answer: str | None = None
    pending_hint: str | None = None
    pending_prompt: str | None = None


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


Event = Start | PhotoOnly | StudentText | Action


def reduce_turn(state: TrainState, event: Event) -> Turn:
    current = TrainState(**asdict(state))
    if isinstance(event, Start):
        return Turn(current, [Reply(GREETING)])
    if isinstance(event, PhotoOnly):
        if current.mode == "submission":
            return Turn(current, [Reply(SUBMISSION_PHOTO)])
        return Turn(current, [Reply(TRAINING_PHOTO)])
    if isinstance(event, Action):
        return _on_action(current, event)
    if current.mode == "submission" and current.step != "check":
        return Turn(current, [Reply(SUBMISSION_TEXT)])
    if current.step == "check" and current.pending_answer:
        return _grade(current, event.text)
    return _ask(current, event.text)


def _ask(state: TrainState, text: str) -> Turn:
    title = detect_topic(text)
    if title is None:
        buttons = tuple(ButtonSpec(item.title, "pick", item.title) for item in TOPICS)
        return Turn(state, [Reply(UNKNOWN_TOPIC, buttons=buttons)])
    return _open_topic(state, title)


def _on_action(state: TrainState, event: Action) -> Turn:
    if event.name in {"pick", "review"} and event.topic_title:
        return _open_topic(state, event.topic_title)
    material = topic_by_title(state.topic_title or "")
    if material is None:
        buttons = tuple(ButtonSpec(item.title, "pick", item.title) for item in TOPICS)
        return Turn(state, [Reply(UNKNOWN_TOPIC, buttons=buttons)])
    if event.name == "more_example":
        state.example_index += 1
        state.step = "explain"
        return Turn(state, [_explain_reply(material, state.example_index)])
    if event.name in {"to_practice", "again"}:
        if event.name == "again":
            state.task_index += 1
        return _practice(state, material)
    return Turn(state, [Reply("Напиши вопрос или выбери тему.")])


def _open_topic(state: TrainState, title: str) -> Turn:
    material = topic_by_title(title)
    if material is None:
        return Turn(state, [Reply(UNKNOWN_TOPIC)])
    state.topic_title = material.title
    state.step = "explain"
    state.example_index = 0
    state.task_index = 0
    state.pending_answer = None
    state.pending_hint = None
    state.pending_prompt = None
    return Turn(state, [_explain_reply(material, 0)])


def _explain_reply(material: TopicMaterial, example_index: int) -> Reply:
    example = material.examples[example_index % len(material.examples)]
    return Reply(
        lead=material.explanation,
        body=f"Пример. {example.text}",
        buttons=(
            ButtonSpec("Ещё пример", "more_example"),
            ButtonSpec("К практике", "to_practice"),
        ),
        replaceable_lead=True,
        topic_title=material.title,
    )


def _practice(state: TrainState, material: TopicMaterial) -> Turn:
    task = material.tasks[state.task_index % len(material.tasks)]
    state.step = "check"
    state.pending_answer = task.answer
    state.pending_hint = task.hint
    state.pending_prompt = task.prompt
    return Turn(state, [Reply(f"Задание. {task.prompt}")])


def _grade(state: TrainState, answer: str) -> Turn:
    expected = state.pending_answer or ""
    correct = answers_match(expected, answer)
    hint = state.pending_hint or "Пройди приём из объяснения ещё раз."
    feedback = "Верно." if correct else f"Пока не сходится. {hint}"
    draft = AttemptDraft(
        topic_title=state.topic_title or "",
        prompt=state.pending_prompt or "",
        expected=expected,
        answer=answer.strip(),
        correct=correct,
        feedback=feedback,
        hint=hint,
    )
    state.step = "done"
    state.pending_answer = None
    state.pending_hint = None
    state.pending_prompt = None
    return Turn(
        state,
        [Reply(feedback, buttons=(ButtonSpec("Ещё задание", "again"),))],
        attempt=draft,
    )


SUBMISSION_UNAVAILABLE = (
    "Сдача появится, когда учитель отправит работу. Личный вопрос учителю не передаётся."
)


def present_turn(turn: Turn, status_line: str | None = None) -> dict:
    """Lesson payload for the student. Never includes the reference answer."""
    reply = turn.replies[-1] if turn.replies else None
    lead = reply.lead if reply else ""
    body = reply.body if reply else ""
    explanation = None
    example = None
    task = None
    feedback = None
    notice = None
    if turn.attempt is not None:
        feedback = lead or None
        task = turn.attempt.prompt or None
    elif reply is not None and reply.replaceable_lead:
        explanation = lead or None
        if body.startswith("Пример."):
            example = body.split("Пример.", 1)[1].strip() or None
        elif body:
            example = body
    elif turn.state.step == "check":
        if lead.startswith("Задание."):
            task = lead.split("Задание.", 1)[1].strip() or None
        else:
            task = lead or None
    else:
        notice = lead or None
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
        "feedback": feedback,
        "correct": None if turn.attempt is None else turn.attempt.correct,
        "given": None if turn.attempt is None else turn.attempt.answer,
        "actions": actions,
        "notice": notice,
        "status_line": status_line,
        "awaiting_answer": turn.state.step == "check" and bool(turn.state.pending_answer),
        "photo_received": False,
        "photo_note": None,
    }


def present_state(state: TrainState) -> dict:
    if state.mode == "submission" and state.step != "check":
        view = _blank_lesson(state)
        view["notice"] = "Открыта сдача. Новую страницу здесь не разбираю."
        return view
    material = topic_by_title(state.topic_title or "")
    if state.step == "explain" and material is not None:
        clone = TrainState(**asdict(state))
        return present_turn(Turn(clone, [_explain_reply(material, clone.example_index)]))
    if state.step == "check" and state.pending_prompt:
        clone = TrainState(**asdict(state))
        return present_turn(Turn(clone, [Reply(f"Задание. {clone.pending_prompt}")]))
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
        "feedback": None,
        "correct": None,
        "given": None,
        "actions": [],
        "notice": None,
        "status_line": None,
        "awaiting_answer": False,
        "photo_received": False,
        "photo_note": None,
    }
