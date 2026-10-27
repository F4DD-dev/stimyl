import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.updates import Incoming, parse_update
from app.core.config import Settings
from app.db.models import (
    Attempt,
    ClassTeacher,
    Enrollment,
    InboundEvent,
    LearningSession,
    Message,
    SchoolClass,
    Topic,
    TopicState,
    User,
)
from app.domain.curriculum import DEMO_CLASS_TITLE
from app.domain.progress import STATUS_LABEL, TopicProgress, choose_next, streak
from app.domain.report import StateFact, TopicColumn, build_report
from app.domain.status import Thresholds, TopicStatus, correct_ratio, decide_status
from app.domain.training import (
    Action,
    ButtonSpec,
    PhotoOnly,
    Reply,
    Start,
    StudentText,
    TrainState,
    Turn,
    reduce_turn,
)
from app.llm.explainer import Explainer
from app.max_client.base import OutboundButton

logger = logging.getLogger(__name__)


async def process_update(
    session: AsyncSession,
    update: dict,
    sender: object,
    explainer: Explainer,
    settings: Settings,
) -> None:
    incoming = parse_update(update)
    if incoming is None:
        return
    if incoming.dedup_key and await _seen(session, incoming.dedup_key):
        if incoming.callback_id:
            await sender.answer_callback(incoming.callback_id, None)
        return
    if incoming.dedup_key:
        session.add(InboundEvent(dedup_key=incoming.dedup_key))
        await session.flush()

    user = await _ensure_person(session, incoming, settings)
    topics = await _topics(session)
    title_to_id = {topic.title: topic.id for topic in topics}
    id_to_title = {topic.id: topic.title for topic in topics}
    row, state = await _load_state(session, user, id_to_title)
    if row is None:
        row = _new_session(user)
        session.add(row)
        await session.flush()
    if incoming.photo_token or incoming.photo_url:
        row.photo_token = incoming.photo_token
        row.photo_url = incoming.photo_url
        row.photo_expires_at = datetime.now(UTC) + timedelta(days=settings.photo_ttl_days)

    turn = reduce_turn(state, _event(incoming, id_to_title))
    await _apply_explainer(turn, explainer)
    _save_state(row, turn.state, title_to_id)
    visibility = "private" if turn.state.mode == "training" else "submission"
    if incoming.text:
        _add_message(session, row, "student", incoming.text, visibility)
    if turn.attempt:
        topic_id = title_to_id.get(turn.attempt.topic_title)
        if topic_id is not None:
            now = datetime.now(UTC)
            session.add(
                Attempt(
                    user_id=user.id,
                    topic_id=topic_id,
                    session_id=row.id,
                    mode=turn.state.mode,
                    prompt=turn.attempt.prompt[:500],
                    expected=turn.attempt.expected[:64],
                    answer=turn.attempt.answer[:200],
                    correct=turn.attempt.correct,
                    feedback=turn.attempt.feedback[:1000],
                    created_at=now,
                )
            )
            await session.flush()
            await _recompute(
                session,
                user.id,
                topic_id,
                _today(settings),
                Thresholds(settings.status_repeat_below, settings.status_mastered_from),
            )
            line, review_title = await _progress_line(session, user.id, settings, topic_id)
            reply = turn.replies[-1]
            reply.lead = f"{reply.lead}\n\n{line}"
            if review_title:
                reply.buttons = reply.buttons + (
                    ButtonSpec("Разобрать с ботом", "review", review_title),
                )
    for reply in turn.replies:
        _add_message(session, row, "bot", reply.text, visibility)
    if incoming.callback_id:
        await sender.answer_callback(incoming.callback_id, None)
    await _deliver(sender, incoming, turn.replies, title_to_id)


async def _seen(session: AsyncSession, key: str) -> bool:
    found = await session.scalar(select(InboundEvent.id).where(InboundEvent.dedup_key == key))
    return found is not None


async def _ensure_person(session: AsyncSession, incoming: Incoming, settings: Settings) -> User:
    found = await session.scalar(select(User).where(User.max_user_id == incoming.max_user_id))
    if found is not None:
        return found
    role = (
        "teacher"
        if settings.teacher_max_user_id and incoming.max_user_id == settings.teacher_max_user_id
        else "student"
    )
    found = User(max_user_id=incoming.max_user_id, role=role, display_name=incoming.name)
    session.add(found)
    await session.flush()
    school = await session.scalar(select(SchoolClass).where(SchoolClass.title == DEMO_CLASS_TITLE))
    if school is None:
        logger.error("demo class is missing")
        return found
    if role == "teacher":
        session.add(ClassTeacher(class_id=school.id, user_id=found.id))
    else:
        session.add(Enrollment(class_id=school.id, user_id=found.id))
    await session.flush()
    return found


async def _topics(session: AsyncSession) -> list[Topic]:
    return list(await session.scalars(select(Topic).order_by(Topic.position)))


def _event(incoming: Incoming, id_to_title: dict[int, str]):
    if incoming.kind == "start":
        return Start()
    if incoming.kind == "photo":
        return PhotoOnly()
    if incoming.kind == "callback":
        payload = incoming.payload or ""
        if ":" in payload:
            name, raw = payload.split(":", 1)
            title = id_to_title.get(int(raw)) if raw.isdigit() else None
            return Action(name, title)
        return Action(payload)
    return StudentText(incoming.text or "")


async def _load_state(
    session: AsyncSession,
    user: User,
    id_to_title: dict[int, str],
) -> tuple[LearningSession | None, TrainState]:
    row = await session.scalar(
        select(LearningSession)
        .where(LearningSession.user_id == user.id)
        .order_by(LearningSession.id.desc())
        .limit(1)
    )
    if row is None:
        return None, TrainState()
    _expire_photo(row)
    title = id_to_title.get(row.topic_id) if row.topic_id is not None else None
    return row, TrainState(
        mode=row.mode,
        step=row.step,
        topic_title=title,
        example_index=row.example_index,
        task_index=row.task_index,
        pending_answer=row.pending_answer,
        pending_hint=row.pending_hint,
        pending_prompt=row.pending_prompt,
    )


def _new_session(user: User) -> LearningSession:
    return LearningSession(
        user_id=user.id,
        mode="training",
        step="done",
        example_index=0,
        task_index=0,
        created_at=datetime.now(UTC),
    )


def _expire_photo(row: LearningSession) -> None:
    if row.photo_expires_at is None:
        return
    expires = row.photo_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        row.photo_token = None
        row.photo_url = None
        row.photo_expires_at = None


def _save_state(row: LearningSession, state: TrainState, title_to_id: dict[str, int]) -> None:
    row.mode = state.mode
    row.step = state.step
    row.topic_id = title_to_id.get(state.topic_title or "")
    row.example_index = state.example_index
    row.task_index = state.task_index
    row.pending_answer = state.pending_answer
    row.pending_hint = state.pending_hint
    row.pending_prompt = state.pending_prompt


def _add_message(
    session: AsyncSession,
    row: LearningSession,
    role: str,
    text: str,
    visibility: str,
) -> None:
    session.add(
        Message(
            session_id=row.id,
            role=role,
            text=text[:4000],
            visibility=visibility,
            created_at=datetime.now(UTC),
        )
    )


async def _apply_explainer(turn: Turn, explainer: Explainer) -> None:
    for reply in turn.replies:
        if reply.replaceable_lead and reply.topic_title:
            generated = await explainer.explain_topic(reply.topic_title)
            if generated:
                reply.lead = generated.strip()[:800]
    if turn.attempt is None or turn.attempt.correct:
        return
    generated = await explainer.explain_mistake(turn.attempt.topic_title, turn.attempt.hint)
    if generated and turn.attempt.expected not in generated:
        turn.replies[-1].lead = f"Пока не сходится. {generated.strip()[:500]}"
        turn.attempt.feedback = turn.replies[-1].lead


async def _recompute(
    session: AsyncSession,
    user_id: int,
    topic_id: int,
    today,
    thresholds: Thresholds,
) -> None:
    flags = [
        bool(item)
        for item in await session.scalars(
            select(Attempt.correct)
            .where(Attempt.user_id == user_id, Attempt.topic_id == topic_id)
            .order_by(Attempt.id)
        )
    ]
    status = decide_status(flags, thresholds)
    if status is None:
        return
    state = await session.scalar(
        select(TopicState).where(TopicState.user_id == user_id, TopicState.topic_id == topic_id)
    )
    ratio = correct_ratio(flags)
    recheck = any(flags[1:])
    if state is None:
        session.add(
            TopicState(
                user_id=user_id,
                topic_id=topic_id,
                status=status.value,
                correct_ratio=ratio,
                attempts_count=len(flags),
                has_recheck=recheck,
                last_attempt_on=today,
            )
        )
        return
    state.status = status.value
    state.correct_ratio = ratio
    state.attempts_count = len(flags)
    state.has_recheck = recheck
    state.last_attempt_on = today


async def _progress_line(
    session: AsyncSession,
    user_id: int,
    settings: Settings,
    topic_id: int,
) -> tuple[str, str | None]:
    topics = await _topics(session)
    stored = {
        row.topic_id: row
        for row in await session.scalars(select(TopicState).where(TopicState.user_id == user_id))
    }
    rows: list[TopicProgress] = []
    for topic in topics:
        state = stored.get(topic.id)
        if state is None:
            rows.append(TopicProgress(topic.title, topic.position, None, None))
        else:
            rows.append(
                TopicProgress(
                    topic.title,
                    topic.position,
                    TopicStatus(state.status),
                    round(state.correct_ratio * 100),
                )
            )
    step = choose_next(rows)
    practiced = stored.get(topic_id)
    if practiced is None:
        label = step.label if step else ""
        return label, step.topic_title if step else None
    title = next(topic.title for topic in topics if topic.id == topic_id)
    status = TopicStatus(practiced.status)
    line = (
        f"Тема «{title}»: {STATUS_LABEL[status]}. Верных {round(practiced.correct_ratio * 100)}%."
    )
    if step:
        line = f"{line}\n{step.label}"
    return line, step.topic_title if step else None


def _today(settings: Settings):
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(settings.app_timezone)).date()


def _zone(settings: Settings):
    from zoneinfo import ZoneInfo

    return ZoneInfo(settings.app_timezone)


async def _deliver(
    sender: object, incoming: Incoming, replies: list[Reply], title_to_id: dict[str, int]
) -> None:
    for reply in replies:
        buttons: list[OutboundButton] = []
        for spec in reply.buttons:
            if spec.topic_title:
                topic_id = title_to_id.get(spec.topic_title)
                if topic_id is None:
                    continue
                payload = f"{spec.action}:{topic_id}"
            else:
                payload = spec.action
            buttons.append(OutboundButton(spec.text, payload))
        await sender.send_text(
            user_id=incoming.max_user_id,
            chat_id=incoming.chat_id,
            text=reply.text,
            buttons=buttons,
        )


async def class_report(session: AsyncSession, teacher: User, settings: Settings):
    class_id = await session.scalar(
        select(ClassTeacher.class_id).where(ClassTeacher.user_id == teacher.id)
    )
    if class_id is None:
        return None
    class_title = await session.scalar(select(SchoolClass.title).where(SchoolClass.id == class_id))
    student_rows = (
        await session.execute(
            select(User.id, User.display_name)
            .join(Enrollment, Enrollment.user_id == User.id)
            .where(Enrollment.class_id == class_id, User.role == "student")
            .order_by(User.id)
        )
    ).all()
    topic_rows = (
        await session.execute(
            select(Topic.id, Topic.title, Topic.position).order_by(Topic.position)
        )
    ).all()
    names = {row.id: row.display_name for row in student_rows}
    state_rows = (
        await session.execute(
            select(
                TopicState.user_id,
                Topic.title,
                TopicState.status,
                TopicState.correct_ratio,
                TopicState.last_attempt_on,
            ).join(Topic, Topic.id == TopicState.topic_id)
        )
    ).all()
    if names:
        wrong_rows = (
            await session.execute(
                select(Topic.title, func.count())
                .join(Attempt, Attempt.topic_id == Topic.id)
                .where(Attempt.correct.is_(False), Attempt.user_id.in_(names.keys()))
                .group_by(Topic.title)
            )
        ).all()
    else:
        wrong_rows = []
    states = {}
    for user_id, title, status, ratio, last_on in state_rows:
        if user_id not in names:
            continue
        states[(names[user_id], title)] = StateFact(
            TopicStatus(status),
            round(ratio * 100),
            last_on,
        )
    wrong = {title: count for title, count in wrong_rows}
    return build_report(
        class_title or "",
        [TopicColumn(title, position) for _id, title, position in topic_rows],
        [row.display_name for row in student_rows],
        states,
        wrong,
        _today(settings),
    )


async def student_progress(session: AsyncSession, user: User, settings: Settings) -> dict:
    topics = await _topics(session)
    stored = {
        row.topic_id: row
        for row in await session.scalars(select(TopicState).where(TopicState.user_id == user.id))
    }
    moments = list(
        await session.scalars(select(Attempt.created_at).where(Attempt.user_id == user.id))
    )
    zone = _zone(settings)
    days = set()
    for moment in moments:
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        days.add(moment.astimezone(zone).date())
    rows = []
    payload_topics = []
    for topic in topics:
        state = stored.get(topic.id)
        if state is None:
            rows.append(TopicProgress(topic.title, topic.position, None, None))
            payload_topics.append({"title": topic.title, "status": None, "correct_percent": None})
        else:
            status = TopicStatus(state.status)
            share = round(state.correct_ratio * 100)
            rows.append(TopicProgress(topic.title, topic.position, status, share))
            payload_topics.append(
                {"title": topic.title, "status": status.value, "correct_percent": share}
            )
    step = choose_next(rows)
    completed = await session.scalar(
        select(func.count()).select_from(Attempt).where(Attempt.user_id == user.id)
    )
    return {
        "display_name": user.display_name,
        "streak_days": streak(days, _today(settings)),
        "completed_tasks": int(completed or 0),
        "topics": payload_topics,
        "next_step": step.label if step else None,
    }
