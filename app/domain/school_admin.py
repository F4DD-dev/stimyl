"""Назначение учителя-администратора класса 8Б. Ищет человека по id MAX, не по имени."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    AuthIdentity,
    ClassSubjectTeacher,
    ClassTeacher,
    Enrollment,
    JoinApplication,
    SchoolClass,
    Subject,
    User,
)
from app.domain.onboarding import (
    BOOTSTRAP_KEY,
    CLASS_TITLE,
    SUBJECT_TITLE,
    active_managers,
    claims_for,
    enqueue_notice,
    ensure_prototype,
    prototype_class,
)

BOT = "max"


@dataclass(frozen=True)
class PersonCard:
    found: bool
    text: str
    user_id: int | None = None
    max_id: str = ""
    manages: bool = False


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    changed: bool
    text: str


def _now() -> datetime:
    return datetime.now(UTC)


async def find_by_max(session: AsyncSession, max_id: str) -> tuple[User | None, str]:
    cleaned = max_id.strip()
    if not cleaned.isdigit():
        return None, "Нужен id MAX из колонки max команды users. Имя не подходит."
    identity = await session.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == BOT,
            AuthIdentity.external_id == cleaned,
            AuthIdentity.revoked_at.is_(None),
        )
    )
    if identity is None:
        return None, (
            f"Пользователя с id MAX {cleaned} нет. "
            "Сначала этот человек нажимает «Согласен» в боте. Команда не создаёт людей."
        )
    user = await session.get(User, identity.user_id)
    if user is None or user.deleted_at is not None:
        return None, f"Учётная запись id MAX {cleaned} закрыта."
    return user, ""


async def describe_person(session: AsyncSession, max_id: str) -> PersonCard:
    user, error = await find_by_max(session, max_id)
    if user is None:
        return PersonCard(False, error, max_id=max_id.strip())
    classes = list(
        await session.scalars(
            select(SchoolClass.title)
            .join(ClassTeacher, ClassTeacher.class_id == SchoolClass.id)
            .where(ClassTeacher.user_id == user.id)
            .order_by(SchoolClass.title)
        )
    )
    bound = ", ".join(classes) if classes else "к классу не привязан"
    text = (
        f"id {user.id}, MAX {max_id.strip()}, {user.display_name}, "
        f"роль {user.role}, статус {user.status}, "
        f"управление {'да' if user.can_manage_school else 'нет'}, класс: {bound}"
    )
    return PersonCard(True, text, user.id, max_id.strip(), user.can_manage_school)


async def grant_school_manager(
    session: AsyncSession, max_id: str, *, apply: bool
) -> CommandResult:
    card = await describe_person(session, max_id)
    if not card.found or card.user_id is None:
        return CommandResult(False, False, card.text)
    school_class = await prototype_class(session)
    class_note = school_class.title if school_class is not None else CLASS_TITLE
    plan = (
        f"{card.text}\n"
        f"Будет: роль teacher, управление да, класс {class_note}, предмет {SUBJECT_TITLE}.\n"
        "Повторный первый вход после этого место не откроет."
    )
    if not apply:
        return CommandResult(True, False, plan + "\nИзменений нет. Чтобы записать, добавь --yes.")
    school_class, subject = await ensure_prototype(session)
    user = await session.get(User, card.user_id)
    if user is None:
        return CommandResult(False, False, card.text)
    await _consume_bootstrap(session)
    await _seat_manager(session, user, school_class, subject.id)
    session.add(
        AuditLog(
            actor_user_id=None,
            action="grant_school_manager",
            target_user_id=user.id,
            ip=None,
            detail=f"max {card.max_id} class {school_class.title}"[:300],
            created_at=_now(),
        )
    )
    waiting = await _pending_count(session, school_class.id)
    if waiting:
        await enqueue_notice(
            session,
            user.id,
            kind="join_queue",
            title=f"Заявки в класс {school_class.title}",
            body=f"В классе {school_class.title} заявок без решения: {waiting}. Напиши «заявки».",
            button_text="Заявки",
            button_payload="apps",
            ref_id=None,
        )
    return CommandResult(
        True,
        True,
        plan + f"\nГотово. {user.display_name} теперь учитель-администратор класса {school_class.title}.",
    )


async def transfer_school_manager(
    session: AsyncSession, source_max: str, target_max: str, *, apply: bool
) -> CommandResult:
    source = await describe_person(session, source_max)
    target = await describe_person(session, target_max)
    if not source.found or source.user_id is None:
        return CommandResult(False, False, f"От кого: {source.text}")
    if not target.found or target.user_id is None:
        return CommandResult(False, False, f"Кому: {target.text}")
    if source.user_id == target.user_id:
        return CommandResult(False, False, "Это один и тот же человек.")
    if not source.manages:
        return CommandResult(False, False, f"Сейчас классом не управляет: {source.text}")
    plan = f"Забрать управление у: {source.text}\nОтдать: {target.text}"
    if not apply:
        return CommandResult(True, False, plan + "\nИзменений нет. Чтобы записать, добавь --yes.")
    first, second = sorted((source.user_id, target.user_id))
    await session.get(User, first, with_for_update=True)
    await session.get(User, second, with_for_update=True)
    source_user = await session.get(User, source.user_id)
    target_user = await session.get(User, target.user_id)
    if source_user is None or target_user is None or not source_user.can_manage_school:
        return CommandResult(False, False, "Управление уже изменилось. Повтори просмотр.")
    school_class, subject = await ensure_prototype(session)
    await _seat_manager(session, target_user, school_class, subject.id)
    source_user.can_manage_school = False
    now = _now()
    session.add(
        AuditLog(
            actor_user_id=source_user.id,
            action="transfer_school_manager",
            target_user_id=target_user.id,
            ip=None,
            detail=f"from {source.max_id} to {target.max_id}"[:300],
            created_at=now,
        )
    )
    await session.flush()
    return CommandResult(
        True,
        True,
        plan + f"\nГотово. Заявки теперь принимает {target_user.display_name}.",
    )


async def class_status(session: AsyncSession) -> str:
    school_class = await prototype_class(session)
    if school_class is None:
        return "Класса 8Б ещё нет. Команда никого не создаёт."
    subject = await session.scalar(select(Subject).where(Subject.title == SUBJECT_TITLE))
    managers = await active_managers(session)
    names = ", ".join(item.display_name for item in managers) or "не назначен"
    students = await session.scalar(
        select(func.count())
        .select_from(Enrollment)
        .where(Enrollment.class_id == school_class.id, Enrollment.status == "active")
    )
    waiting = await _pending_count(session, school_class.id)
    teachers = 0
    if subject is not None:
        teachers = await session.scalar(
            select(func.count())
            .select_from(ClassSubjectTeacher)
            .where(
                ClassSubjectTeacher.class_id == school_class.id,
                ClassSubjectTeacher.subject_id == subject.id,
            )
        )
    subject_title = subject.title if subject is not None else "не найден"
    return (
        f"Класс {school_class.title}\n"
        f"Предмет {subject_title}\n"
        f"Код для входа {school_class.join_code}\n"
        f"Ответственный: {names}\n"
        f"Учеников в классе: {int(students or 0)}\n"
        f"Учителей математики: {int(teachers or 0)}\n"
        f"Заявок без решения: {waiting}"
    )


async def bot_applications(session: AsyncSession, user: User) -> tuple[str, tuple[tuple[str, str], ...]]:
    if user.role != "teacher" or not user.can_manage_school:
        managers = await active_managers(session)
        if user.role != "teacher":
            return "Это команда учителя.", ()
        if not managers:
            waiting = await _pending_count_all(session)
            if waiting:
                return "Ответственный за класс не назначен. Заявки есть, принять их некому.", ()
            return "Ответственный за класс не назначен. Новых заявок нет.", ()
        names = ", ".join(item.display_name for item in managers)
        return f"Заявки принимает {names}. У тебя нет этого права.", ()
    rows = await claims_for(session, user)
    if not rows:
        return "Заявок нет.", ()
    buttons = []
    for row in rows[:8]:
        label = row["display_name"][:40]
        buttons.append((f"Принять {label}", f"approve:{row['user_id']}"))
        buttons.append((f"Отклонить {label}", f"reject:{row['user_id']}"))
    return "Кто просится в класс.", tuple(buttons)


async def bot_students(session: AsyncSession, user: User) -> str:
    if user.role != "teacher":
        return "Список учеников видит учитель."
    class_ids = list(
        await session.scalars(
            select(ClassTeacher.class_id).where(ClassTeacher.user_id == user.id)
        )
    )
    if user.can_manage_school:
        prototype_row = await prototype_class(session)
        prototype = prototype_row.id if prototype_row is not None else None
        if prototype is not None and prototype not in class_ids:
            class_ids.append(prototype)
    if not class_ids:
        return "Тебя ещё не назначили на класс."
    rows = (
        await session.execute(
            select(User.display_name, Enrollment.status, SchoolClass.title)
            .join(Enrollment, Enrollment.user_id == User.id)
            .join(SchoolClass, SchoolClass.id == Enrollment.class_id)
            .where(Enrollment.class_id.in_(class_ids), User.deleted_at.is_(None))
            .order_by(SchoolClass.title, User.display_name)
        )
    ).all()
    if not rows:
        return "В классе пока никого нет."
    lines = []
    for name, status, title in rows:
        state = "в классе" if status == "active" else "заявка ждёт"
        lines.append(f"{name}, {title}, {state}")
    return "\n".join(lines)


async def bot_my_class(session: AsyncSession, user: User) -> tuple[str, tuple[tuple[str, str], ...]]:
    if user.role == "student":
        if user.status == "pending":
            return "Твоя заявка ещё ждёт решения.", ()
        return "Ты ученик. Кабинет учителя тебе не открыт.", ()
    if user.role != "teacher":
        return "Класс видит учитель или ученик.", ()
    text = await class_status(session)
    buttons = (("Заявки", "apps"), ("Ученики", "students"), ("Войти в кабинет", "web_login"))
    return text, buttons


async def pending_claims_text(session: AsyncSession) -> str:
    rows = (
        await session.execute(
            select(JoinApplication, User, AuthIdentity.external_id, SchoolClass.title)
            .join(User, User.id == JoinApplication.user_id)
            .join(SchoolClass, SchoolClass.id == JoinApplication.class_id)
            .outerjoin(
                AuthIdentity,
                (AuthIdentity.user_id == User.id)
                & (AuthIdentity.provider == BOT)
                & (AuthIdentity.revoked_at.is_(None)),
            )
            .where(JoinApplication.status == "pending", JoinApplication.wanted_role == "student")
            .order_by(JoinApplication.created_at, User.id)
        )
    ).all()
    if not rows:
        return "Заявок нет."
    lines = ["id\tmax\tимя\tкласс\tкогда"]
    for application, person, max_id, title in rows:
        stamp = application.created_at.strftime("%Y-%m-%d %H:%M")
        lines.append(f"{person.id}\t{max_id or '-'}\t{person.display_name}\t{title}\t{stamp}")
    managers = await active_managers(session)
    if not managers:
        lines.append("Ответственный не назначен. Принять эти заявки пока некому.")
    return "\n".join(lines)


async def _seat_manager(
    session: AsyncSession, user: User, school_class: SchoolClass, subject_id: int
) -> None:
    now = _now()
    user.role = "teacher"
    user.status = "active"
    user.can_manage_school = True
    link = await session.scalar(
        select(ClassTeacher).where(
            ClassTeacher.class_id == school_class.id,
            ClassTeacher.user_id == user.id,
        )
    )
    if link is None:
        session.add(ClassTeacher(class_id=school_class.id, user_id=user.id))
    post = await session.scalar(
        select(ClassSubjectTeacher).where(
            ClassSubjectTeacher.class_id == school_class.id,
            ClassSubjectTeacher.user_id == user.id,
            ClassSubjectTeacher.subject_id == subject_id,
        )
    )
    if post is None:
        session.add(
            ClassSubjectTeacher(
                class_id=school_class.id,
                user_id=user.id,
                subject_id=subject_id,
            )
        )
    enrollment = await session.scalar(
        select(Enrollment).where(
            Enrollment.class_id == school_class.id,
            Enrollment.user_id == user.id,
        )
    )
    if enrollment is not None:
        await session.delete(enrollment)
    application = await session.get(JoinApplication, user.id)
    if application is None:
        session.add(
            JoinApplication(
                user_id=user.id,
                wanted_role="teacher",
                school_id=school_class.school_id,
                class_id=school_class.id,
                status="approved",
                created_at=now,
                reviewed_by=user.id,
                reviewed_at=now,
            )
        )
    else:
        application.wanted_role = "teacher"
        application.school_id = school_class.school_id
        application.class_id = school_class.id
        application.status = "approved"
        application.reviewed_by = user.id
        application.reviewed_at = now
    await session.flush()


async def _consume_bootstrap(session: AsyncSession) -> None:
    await session.execute(
        text(
            "INSERT INTO runtime_flags (key, value) VALUES (:key, 'consumed') "
            "ON CONFLICT (key) DO UPDATE SET value = 'consumed'"
        ),
        {"key": BOOTSTRAP_KEY},
    )


async def _pending_count_all(session: AsyncSession) -> int:
    found = await session.scalar(
        select(func.count())
        .select_from(JoinApplication)
        .where(JoinApplication.status == "pending", JoinApplication.wanted_role == "student")
    )
    return int(found or 0)


async def _pending_count(session: AsyncSession, class_id: int) -> int:
    found = await session.scalar(
        select(func.count())
        .select_from(JoinApplication)
        .where(
            JoinApplication.class_id == class_id,
            JoinApplication.status == "pending",
            JoinApplication.wanted_role == "student",
        )
    )
    return int(found or 0)
