from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import assist
from app.bot.assist import wants_guide, wants_practice
from app.bot.gate import GateReply, open_gate
from app.bot.teacher_chat import is_teacher_action, teacher_turn
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
    Work,
    WorkRecipient,
)
from app.domain.account_copy import PHOTO_OFF
from app.domain.assist import mentions
from app.domain.curriculum import topic_by_title
from app.domain.messages_ru import LINES, SUBMISSION_UNAVAILABLE
from app.domain.progress import STATUS_LABEL, TopicProgress, choose_next, streak
from app.domain.report import StateFact, TopicColumn, activity_line, build_report
from app.domain.status import Thresholds, TopicStatus, decide_status, mark_of, show_percent
from app.domain.training import (
    Action,
    ButtonSpec,
    PhotoOnly,
    Reply,
    Start,
    StudentText,
    TrainState,
    Turn,
    present_state,
    present_turn,
    reduce_turn,
)
from app.llm.explainer import Explainer
from app.max_client.base import OutboundButton


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
            await sender.answer_callback(incoming.callback_id, notification="Уже обработано")
        return
    if incoming.dedup_key:
        session.add(InboundEvent(dedup_key=incoming.dedup_key))
        await session.flush()

    outcome = await open_gate(session, incoming, settings)
    acked = False
    if outcome.replies:
        acked = await _show_gate(sender, incoming, outcome.replies)
    if outcome.stop or outcome.user is None:
        if incoming.callback_id and not acked:
            await sender.answer_callback(incoming.callback_id, notification="Готово")
        return
    user = outcome.user
    if user.role in {"teacher", "admin"} and explainer.enabled and (
        incoming.kind == "text" or is_teacher_action(incoming.payload)
    ):
        if incoming.kind == "text":
            await _typing(sender, incoming)
        replies = await teacher_turn(
            session,
            explainer,
            user,
            settings,
            text=incoming.text if incoming.kind == "text" else None,
            payload=incoming.payload,
        )
        shown = await _show_gate(sender, incoming, replies)
        if incoming.callback_id and not shown:
            await sender.answer_callback(incoming.callback_id, notification="Готово")
        return
    if incoming.kind == "photo" and not settings.feature_photo:
        await _deliver_plain(sender, incoming, [GateReply(PHOTO_OFF)])
        return
    topics = await _topics(session)
    title_to_id = {topic.title: topic.id for topic in topics}
    id_to_title = {topic.id: topic.title for topic in topics}
    row, state = await _load_state(session, user, id_to_title)
    if row is None:
        row = _new_session(user)
        session.add(row)
        await session.flush()
    has_photo = settings.feature_photo and bool(incoming.photo_token or incoming.photo_url)
    if has_photo:
        row.photo_token = incoming.photo_token
        row.photo_url = incoming.photo_url
        row.photo_expires_at = datetime.now(UTC) + timedelta(days=settings.photo_ttl_days)

    event = _event(incoming, id_to_title)
    turn = await _guided(
        session,
        explainer,
        state,
        event,
        user_id=user.id,
        session_id=row.id,
        photo=await _photo_bytes(sender, incoming) if has_photo and explainer.enabled else None,
        has_photo=has_photo,
        on_wait=lambda: _typing(sender, incoming),
    )
    if turn is None:
        turn = reduce_turn(state, event)
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
                    hinted=turn.attempt.hinted,
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
    if incoming.kind == "start" and turn.replies:
        _offer_app(turn.replies[0], user.role)
    for reply in turn.replies:
        _add_message(session, row, "bot", reply.text, visibility)
    await _deliver(sender, incoming, turn.replies, title_to_id, turn.state.version)
    if incoming.callback_id and not acked:
        await sender.answer_callback(incoming.callback_id, notification="Готово")


async def _guided(
    session: AsyncSession,
    explainer: Explainer,
    state: TrainState,
    event,
    *,
    user_id: int,
    session_id: int | None,
    photo: bytes | None,
    has_photo: bool,
    on_wait=None,
) -> Turn | None:
    """Ход через модель или None, если отвечает обычный сценарий."""
    if not explainer.enabled:
        return None
    if isinstance(event, Action):
        stale = event.version is not None and event.version != state.version
        if stale or not wants_practice(state, event.name):
            return None
        if on_wait:
            await on_wait()
        return await assist.practice(session, explainer, state, user_id=user_id)
    text = event.text if isinstance(event, StudentText) else ""
    if not isinstance(event, (StudentText, PhotoOnly)):
        return None
    if not wants_guide(state, text=text, photo=has_photo):
        return None
    if has_photo and photo is None and not text:
        return None
    if on_wait:
        await on_wait()
    return await assist.guide(
        session,
        explainer,
        state,
        user_id=user_id,
        session_id=session_id,
        text=text,
        photo=photo,
    )


async def _typing(sender: object, incoming: Incoming) -> None:
    typing = getattr(sender, "typing", None)
    if typing is not None and incoming.chat_id is not None:
        await typing(incoming.chat_id)


async def _photo_bytes(sender: object, incoming: Incoming) -> bytes | None:
    download = getattr(sender, "download", None)
    if download is None or not incoming.photo_url:
        return None
    return await download(incoming.photo_url)


async def _seen(session: AsyncSession, key: str) -> bool:
    found = await session.scalar(select(InboundEvent.id).where(InboundEvent.dedup_key == key))
    return found is not None


async def _topics(session: AsyncSession) -> list[Topic]:
    return list(await session.scalars(select(Topic).order_by(Topic.position)))


def _custom_topic(topics: list[Topic], action: str | None, title: str | None) -> Topic | None:
    if action != "pick" or not title or topic_by_title(title) is not None:
        return None
    return next((item for item in topics if item.title == title), None)


async def _class_activity(session: AsyncSession, class_id: int, students) -> dict[str, str]:
    ids = [row.id for row in students]
    if not ids:
        return {}
    names = {row.id: row.display_name for row in students}
    lessons = (
        await session.execute(
            select(
                LearningSession.user_id,
                LearningSession.mode,
                LearningSession.step,
                Topic.title,
            )
            .outerjoin(Topic, Topic.id == LearningSession.topic_id)
            .where(LearningSession.user_id.in_(ids))
            .order_by(LearningSession.id.desc())
        )
    ).all()
    latest: dict[int, tuple[str, str, str | None]] = {}
    for user_id, mode, step, title in lessons:
        if user_id not in latest:
            latest[user_id] = (mode, step, title)
    open_rows = (
        await session.execute(
            select(WorkRecipient.user_id, Work.title)
            .join(Work, Work.id == WorkRecipient.work_id)
            .where(
                WorkRecipient.user_id.in_(ids),
                WorkRecipient.status == "assigned",
                Work.status == "published",
                Work.class_id == class_id,
            )
            .order_by(Work.id.desc())
        )
    ).all()
    waiting: dict[int, str] = {}
    for user_id, title in open_rows:
        if user_id not in waiting:
            waiting[user_id] = title
    lines = {}
    for user_id, name in names.items():
        mode, step, title = latest.get(user_id, (None, None, None))
        lines[name] = activity_line(mode=mode, step=step, title=title, open_work=waiting.get(user_id))
    return lines


def _event(incoming: Incoming, id_to_title: dict[int, str]):
    if incoming.kind == "start":
        return Start()
    if incoming.kind == "photo":
        return PhotoOnly()
    if incoming.kind == "callback":
        payload = incoming.payload or ""
        if payload.startswith("v") and ":" in payload:
            head, rest = payload.split(":", 1)
            number = head[1:]
            if number.isdigit():
                version = int(number)
                if ":" in rest:
                    name, raw = rest.split(":", 1)
                    title = id_to_title.get(int(raw)) if raw.isdigit() else None
                    return Action(name, title, version)
                return Action(rest, version=version)
        return Action(payload or "stale", version=-1)
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
        level=row.level,
        correct_streak=row.correct_streak,
        wrong_streak=row.wrong_streak,
        hint_step=row.hint_step,
        task_misses=row.task_misses,
        version=row.state_version,
        line_cursor=row.line_cursor,
        last_line=row.last_line,
        pending_answer=row.pending_answer,
        pending_hint=row.pending_hint,
        pending_step=row.pending_step,
        pending_prompt=row.pending_prompt,
        pending_text=row.pending_text,
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
    row.level = state.level
    row.correct_streak = state.correct_streak
    row.wrong_streak = state.wrong_streak
    row.hint_step = state.hint_step
    row.task_misses = state.task_misses
    row.state_version = state.version
    row.line_cursor = state.line_cursor
    row.last_line = state.last_line
    row.pending_answer = state.pending_answer
    row.pending_hint = state.pending_hint
    row.pending_step = state.pending_step
    row.pending_prompt = state.pending_prompt
    row.pending_text = state.pending_text


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
    generated = await explainer.explain_mistake(
        turn.attempt.topic_title,
        turn.attempt.hint,
        prompt=turn.attempt.prompt,
        answer=turn.attempt.answer,
    )
    if generated and not mentions(generated, turn.attempt.expected) and len(turn.replies) == 1:
        turn.replies[-1].lead = f"{LINES['wrong'][0]} {generated.strip()[:500]}"
        turn.attempt.feedback = turn.replies[-1].lead


async def _recompute(
    session: AsyncSession,
    user_id: int,
    topic_id: int,
    today,
    thresholds: Thresholds,
) -> None:
    rows = (
        await session.execute(
            select(Attempt.correct, Attempt.prompt, Attempt.created_at, Attempt.hinted)
            .where(Attempt.user_id == user_id, Attempt.topic_id == topic_id)
            .order_by(Attempt.id)
        )
    ).all()
    marks = [
        mark_of(bool(correct), hinted=bool(hinted), prompt=prompt, at=moment)
        for correct, prompt, moment, hinted in rows
    ]
    status = decide_status(marks, thresholds)
    if status is None:
        return
    state = await session.scalar(
        select(TopicState).where(TopicState.user_id == user_id, TopicState.topic_id == topic_id)
    )
    window = marks[-10:]
    ratio = sum(item.credit for item in window) / len(window) if window else 0.0
    recheck = status is TopicStatus.mastered
    if state is None:
        session.add(
            TopicState(
                user_id=user_id,
                topic_id=topic_id,
                status=status.value,
                correct_ratio=ratio,
                attempts_count=len(marks),
                has_recheck=recheck,
                last_attempt_on=today,
            )
        )
        return
    state.status = status.value
    state.correct_ratio = ratio
    state.attempts_count = len(marks)
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
                    attempts=state.attempts_count,
                    rank_score=state.correct_ratio,
                )
            )
    step = choose_next(rows)
    practiced = stored.get(topic_id)
    if practiced is None:
        label = step.label if step else ""
        return label, step.topic_title if step else None
    title = next(topic.title for topic in topics if topic.id == topic_id)
    status = TopicStatus(practiced.status)
    if show_percent(status):
        line = (
            f"Тема «{title}»: {STATUS_LABEL[status]}. "
            f"Верных {round(practiced.correct_ratio * 100)}%."
        )
    else:
        line = f"Тема «{title}»: {STATUS_LABEL[status]}."
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
    sender: object,
    incoming: Incoming,
    replies: list[Reply],
    title_to_id: dict[str, int],
    version: int,
) -> None:
    for reply in replies:
        buttons: list[OutboundButton] = []
        for spec in reply.buttons:
            if spec.topic_title:
                topic_id = title_to_id.get(spec.topic_title)
                if topic_id is None:
                    continue
                payload = f"v{version}:{spec.action}:{topic_id}"
            else:
                payload = f"v{version}:{spec.action}"
            buttons.append(OutboundButton(spec.text, payload))
        await sender.send_text(
            user_id=incoming.max_user_id,
            chat_id=incoming.chat_id,
            text=reply.text,
            buttons=buttons,
        )


def _offer_app(reply: Reply, role: str) -> None:
    if role in {"teacher", "admin"}:
        spec = ButtonSpec("Открыть кабинет", "open_cabinet")
    else:
        spec = ButtonSpec("Мой прогресс", "progress")
    reply.buttons = reply.buttons + (spec,)


def _gate_buttons(replies: list[GateReply]) -> list[OutboundButton]:
    buttons: list[OutboundButton] = []
    for reply in replies:
        buttons.extend(OutboundButton(text, payload) for text, payload in reply.buttons)
        if reply.request_contact:
            buttons.append(OutboundButton("Поделиться номером", "", request_contact=True))
        if reply.app_payload and reply.app_name:
            buttons.append(
                OutboundButton(
                    reply.app_text or "Открыть",
                    reply.app_payload,
                    web_app=reply.app_name,
                    contact_id=reply.app_contact,
                )
            )
        if reply.link_url:
            buttons.append(OutboundButton(reply.link_text or "Открыть", "", reply.link_url))
    return buttons


async def _show_gate(sender: object, incoming: Incoming, replies: list[GateReply]) -> bool:
    """Показать ответ входа. На кнопке сначала меняем её сообщение, иначе шлём новое."""
    text = "\n\n".join(reply.text for reply in replies if reply.text)
    buttons = _gate_buttons(replies)
    if incoming.callback_id and (text or buttons):
        shown = await sender.answer_callback(incoming.callback_id, text=text or None, buttons=buttons)
        if shown:
            return True
    await _deliver_plain(sender, incoming, replies)
    return False


async def _deliver_plain(sender: object, incoming: Incoming, replies: list[GateReply]) -> None:
    for reply in replies:
        own = _gate_buttons([reply])
        await sender.send_text(
            user_id=incoming.max_user_id,
            chat_id=incoming.chat_id,
            text=reply.text,
            buttons=own,
        )


async def class_report(
    session: AsyncSession,
    teacher: User,
    settings: Settings,
    class_id: int | None = None,
):
    query = select(ClassTeacher.class_id).where(ClassTeacher.user_id == teacher.id)
    if class_id is not None:
        query = query.where(ClassTeacher.class_id == class_id)
    class_id = await session.scalar(query.order_by(ClassTeacher.class_id))
    if class_id is None:
        return None
    class_title = await session.scalar(select(SchoolClass.title).where(SchoolClass.id == class_id))
    student_rows = (
        await session.execute(
            select(User.id, User.display_name)
            .join(Enrollment, Enrollment.user_id == User.id)
            .where(
                Enrollment.class_id == class_id,
                Enrollment.status == "active",
                User.role == "student",
                User.deleted_at.is_(None),
            )
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
    activity = await _class_activity(session, class_id, student_rows)
    return build_report(
        class_title or "",
        [TopicColumn(title, position) for _id, title, position in topic_rows],
        [row.display_name for row in student_rows],
        states,
        wrong,
        _today(settings),
        activity=activity,
        student_ids=[row.id for row in student_rows],
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
            share = None if not show_percent(status) else round(state.correct_ratio * 100)
            rows.append(
                TopicProgress(
                    topic.title,
                    topic.position,
                    status,
                    share,
                    attempts=state.attempts_count,
                    rank_score=state.correct_ratio,
                )
            )
            payload_topics.append(
                {"title": topic.title, "status": status.value, "correct_percent": share}
            )
    step = choose_next(rows)
    completed = await session.scalar(
        select(func.count()).select_from(Attempt).where(Attempt.user_id == user.id)
    )
    class_title = await session.scalar(
        select(SchoolClass.title)
        .join(Enrollment, Enrollment.class_id == SchoolClass.id)
        .where(Enrollment.user_id == user.id)
    )
    return {
        "display_name": user.display_name,
        "class_title": class_title,
        "streak_days": streak(days, _today(settings)),
        "completed_tasks": int(completed or 0),
        "topics": payload_topics,
        "next_step": step.label if step else None,
        "next_topic": step.topic_title if step else None,
    }


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.isoformat()


async def current_lesson(session: AsyncSession, user: User) -> dict:
    topics = await _topics(session)
    id_to_title = {topic.id: topic.title for topic in topics}
    _row, state = await _load_state(session, user, id_to_title)
    return present_state(state)


async def student_history(session: AsyncSession, user: User) -> dict:
    session_rows = (
        await session.execute(
            select(
                LearningSession.id,
                LearningSession.mode,
                LearningSession.created_at,
                Topic.title,
            )
            .outerjoin(Topic, Topic.id == LearningSession.topic_id)
            .where(LearningSession.user_id == user.id)
            .order_by(LearningSession.id.desc())
            .limit(30)
        )
    ).all()
    attempt_rows = (
        await session.execute(
            select(Attempt.session_id, Attempt.correct).where(Attempt.user_id == user.id)
        )
    ).all()
    buckets: dict[int, list[bool]] = {}
    for session_id, correct in attempt_rows:
        buckets.setdefault(session_id, []).append(bool(correct))
    items = []
    for row_id, mode, created_at, title in session_rows:
        flags = buckets.get(row_id, [])
        items.append(
            {
                "mode": mode,
                "topic": title,
                "created_at": _iso(created_at),
                "answered": len(flags),
                "correct_count": sum(1 for flag in flags if flag),
            }
        )
    return {"sessions": items}


async def student_turn(
    session: AsyncSession,
    user: User,
    settings: Settings,
    explainer: Explainer,
    *,
    text: str | None = None,
    action: str | None = None,
    topic: str | None = None,
    version: int | None = None,
    photo: bytes | None = None,
) -> dict:
    """Training turn for the mini-app. Submission is refused without storing the text."""
    topics = await _topics(session)
    title_to_id = {item.title: item.id for item in topics}
    id_to_title = {item.id: item.title for item in topics}
    row, state = await _load_state(session, user, id_to_title)
    custom = _custom_topic(topics, action, topic)
    if custom is not None and (row is None or row.mode != "submission"):
        if row is None:
            row = _new_session(user)
            session.add(row)
            await session.flush()
        row.mode = "training"
        row.step = "explain"
        row.topic_id = custom.id
        note = custom.blurb.strip() or f"Тема «{custom.title}». Задания к ней лежат в разделе «Задания»."
        return {
            "ok": True,
            "mode": "training",
            "step": "explain",
            "topic": custom.title,
            "explanation": note,
            "example": None,
            "task": None,
            "feedback": None,
            "correct": None,
            "given": None,
            "actions": [],
            "notice": "Ответы на работу учителя сдаются в заданиях.",
            "status_line": None,
            "version": row.state_version,
            "awaiting_answer": False,
            "photo_received": False,
            "photo_note": None,
        }
    if row is not None and row.mode == "submission":
        return {
            "ok": False,
            "code": "submission_unavailable",
            "detail": SUBMISSION_UNAVAILABLE,
        }
    if row is None:
        row = _new_session(user)
        session.add(row)
        await session.flush()
    state.mode = "training"
    cleaned = (text or "").strip()
    if action:
        event = Action(action, topic, version)
    elif cleaned:
        event = StudentText(cleaned)
    elif photo:
        event = PhotoOnly()
    else:
        return {"ok": False, "code": "empty", "detail": LINES["empty_practice"][0]}
    turn = await _guided(
        session,
        explainer,
        state,
        event,
        user_id=user.id,
        session_id=row.id,
        photo=photo,
        has_photo=photo is not None,
    )
    if turn is None:
        turn = reduce_turn(state, event)
    await _apply_explainer(turn, explainer)
    _save_state(row, turn.state, title_to_id)
    if cleaned and not action:
        _add_message(session, row, "student", cleaned, "private")
    status_line = None
    review_title = None
    if turn.attempt:
        topic_id = title_to_id.get(turn.attempt.topic_title)
        if topic_id is not None:
            now = datetime.now(UTC)
            session.add(
                Attempt(
                    user_id=user.id,
                    topic_id=topic_id,
                    session_id=row.id,
                    mode="training",
                    prompt=turn.attempt.prompt[:500],
                    expected=turn.attempt.expected[:64],
                    answer=turn.attempt.answer[:200],
                    correct=turn.attempt.correct,
                    hinted=turn.attempt.hinted,
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
            status_line, review_title = await _progress_line(session, user.id, settings, topic_id)
    for reply in turn.replies:
        _add_message(session, row, "bot", reply.text, "private")
    view = present_turn(turn, status_line)
    if review_title and not any(item.get("topic") == review_title for item in view["actions"]):
        view["actions"] = [
            *view["actions"],
            {"action": "review", "label": "Разобрать следующий шаг", "topic": review_title},
        ]
    view["photo_received"] = photo is not None
    view["photo_note"] = LINES["photo_note"][0] if photo is not None and not view["explanation"] else None
    return view
