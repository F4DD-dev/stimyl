"""Школы Амурской области и заявка в класс. Список — данные, не ветка кода."""

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ClassTeacher,
    Enrollment,
    JoinApplication,
    School,
    SchoolClass,
    StaffSeat,
    User,
)

DATA = Path(__file__).resolve().parents[1] / "db" / "data" / "amur_schools.json"
PILOT_KEY = "blg-16"
PILOT_CLASS = "5А"
SEATS = (
    ("t1", "Классный руководитель"),
    ("t2", "Математика"),
    ("t3", "Русский язык"),
    ("t4", "История"),
    ("t5", "Английский язык"),
    ("admin", "Администратор школы"),
)


def catalog() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


def cities() -> list[str]:
    return [item["name"] for item in catalog()["cities"]]


def schools_in(city: str) -> list[dict]:
    for item in catalog()["cities"]:
        if item["name"] == city:
            return list(item["schools"])
    return []


async def ensure_directory(session: AsyncSession) -> None:
    """Положить снимок списка и пилотный класс. Повтор ничего не дублирует."""
    data = catalog()
    region = data["region"]
    now = datetime.now(UTC)
    pilot_class_id = None
    pilot_school_id = None
    for city in data["cities"]:
        for item in city["schools"]:
            school = await session.scalar(select(School).where(School.external_key == item["key"]))
            if school is None:
                school = School(
                    title=item["title"][:200],
                    created_at=now,
                    region=region,
                    city=city["name"],
                    external_key=item["key"],
                )
                session.add(school)
                await session.flush()
            if item["key"] != PILOT_KEY:
                continue
            pilot_school_id = school.id
            school_class = await session.scalar(
                select(SchoolClass).where(
                    SchoolClass.school_id == school.id,
                    SchoolClass.title == PILOT_CLASS,
                )
            )
            if school_class is None:
                school_class = SchoolClass(
                    school_id=school.id,
                    title=PILOT_CLASS,
                    join_key="blg-16-5a",
                    join_code="5A16",
                    join_open=True,
                    timezone="Asia/Yakutsk",
                )
                session.add(school_class)
                await session.flush()
            pilot_class_id = school_class.id
    if pilot_school_id is None or pilot_class_id is None:
        return
    for code, title in SEATS:
        found = await session.scalar(
            select(StaffSeat).where(StaffSeat.class_id == pilot_class_id, StaffSeat.code == code)
        )
        if found is None:
            session.add(
                StaffSeat(
                    school_id=pilot_school_id,
                    class_id=pilot_class_id,
                    code=code,
                    title=title,
                )
            )
    await session.flush()


async def placed(session: AsyncSession, user: User) -> bool:
    enrolled = await session.scalar(
        select(Enrollment.user_id).where(
            Enrollment.user_id == user.id,
            Enrollment.status == "active",
        )
    )
    if enrolled is not None:
        return True
    teaches = await session.scalar(
        select(ClassTeacher.user_id).where(ClassTeacher.user_id == user.id)
    )
    return teaches is not None


async def application_of(session: AsyncSession, user: User) -> JoinApplication | None:
    return await session.get(JoinApplication, user.id)


async def is_school_admin(session: AsyncSession, user: User) -> bool:
    seat = await session.scalar(
        select(StaffSeat).where(StaffSeat.user_id == user.id, StaffSeat.code == "admin")
    )
    return seat is not None


def role_reply() -> tuple[str, tuple[tuple[str, str], ...]]:
    return (
        "Кто ты в школе? После выбора учреждения заявка уйдёт администратору.",
        (("Я ученик", "role:student"), ("Я учитель", "role:teacher")),
    )


def city_reply() -> tuple[str, tuple[tuple[str, str], ...]]:
    buttons = tuple((name, f"city:{index}") for index, name in enumerate(cities()))
    return ("Амурская область. Выбери город.", buttons)


def school_reply(city: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    buttons = tuple((item["title"][:120], f"school:{item['key']}") for item in schools_in(city))
    if not buttons:
        return ("В этом городе школ в списке нет. Выбери другой город.", ())
    return (f"{city}. Выбери школу. Открыт набор пока только в Школе 16.", buttons)


async def _draft(session: AsyncSession, user: User, role: str) -> JoinApplication:
    row = await application_of(session, user)
    now = datetime.now(UTC)
    if row is None:
        row = JoinApplication(
            user_id=user.id,
            wanted_role=role,
            status="draft",
            created_at=now,
        )
        session.add(row)
    else:
        row.wanted_role = role
        row.status = "draft"
    await session.flush()
    return row


async def choose_role(session: AsyncSession, user: User, role: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    if role not in {"student", "teacher"}:
        return role_reply()
    await _draft(session, user, role)
    return city_reply()


async def choose_city(session: AsyncSession, user: User, index: int) -> tuple[str, tuple[tuple[str, str], ...]]:
    names = cities()
    if index < 0 or index >= len(names):
        return city_reply()
    row = await application_of(session, user)
    if row is None:
        return role_reply()
    row.city = names[index]
    await session.flush()
    return school_reply(names[index])


async def choose_school(
    session: AsyncSession, user: User, key: str, *, allow_admin_bootstrap: bool
) -> tuple[str, tuple[tuple[str, str], ...]]:
    row = await application_of(session, user)
    if row is None or not row.city:
        return role_reply()
    match = next((item for item in schools_in(row.city) if item["key"] == key), None)
    if match is None:
        return school_reply(row.city)
    school = await session.scalar(select(School).where(School.external_key == key))
    if school is None:
        return ("Эту школу сейчас не найти. Выбери другую.", ())
    row.school_id = school.id
    if not match.get("pilot"):
        row.class_id = None
        row.seat_code = None
        row.status = "draft"
        await session.flush()
        return (
            "В этой школе набор ещё не открыт. Для проверки выбери МАОУ Школа 16 гор. Благовещенск.",
            (("Школа 16", "school:blg-16"),),
        )
    school_class = await session.scalar(
        select(SchoolClass).where(SchoolClass.school_id == school.id, SchoolClass.title == PILOT_CLASS)
    )
    if school_class is None:
        return ("Класс 5А ещё не создан.", ())
    row.class_id = school_class.id
    if row.wanted_role == "student":
        return await _submit(session, user, row, seat=None, allow_admin_bootstrap=allow_admin_bootstrap)
    seats = list(
        await session.scalars(select(StaffSeat).where(StaffSeat.class_id == school_class.id).order_by(StaffSeat.id))
    )
    buttons = tuple((seat.title, f"seat:{seat.code}") for seat in seats)
    return ("Класс 5А. Выбери себя.", buttons)


async def choose_seat(
    session: AsyncSession, user: User, code: str, *, allow_admin_bootstrap: bool
) -> tuple[str, tuple[tuple[str, str], ...]]:
    row = await application_of(session, user)
    if row is None or row.class_id is None:
        return role_reply()
    seat = await session.scalar(
        select(StaffSeat).where(StaffSeat.class_id == row.class_id, StaffSeat.code == code)
    )
    if seat is None:
        return ("Такого места нет.", ())
    if seat.user_id is not None and seat.user_id != user.id:
        return ("Это место уже занято. Выбери другое.", ())
    row.wanted_role = "admin" if code == "admin" else "teacher"
    return await _submit(session, user, row, seat=seat, allow_admin_bootstrap=allow_admin_bootstrap)


async def _submit(
    session: AsyncSession,
    user: User,
    row: JoinApplication,
    *,
    seat: StaffSeat | None,
    allow_admin_bootstrap: bool,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    if seat is not None and seat.code == "admin" and allow_admin_bootstrap:
        await _activate(session, user, row, seat)
        return (
            "Ты администратор Школы 16, класс 5А. Напиши «заявки», чтобы принять учителей и учеников.",
            (("Заявки", "apps"),),
        )
    row.status = "pending"
    if seat is not None:
        row.seat_code = seat.code
    await session.flush()
    return (
        "Заявка ушла администратору Школы 16. Когда её примут, напиши /start.",
        (),
    )


async def _activate(session: AsyncSession, user: User, row: JoinApplication, seat: StaffSeat | None) -> None:
    row.status = "approved"
    if row.wanted_role == "student" and row.class_id is not None:
        user.role = "student"
        user.status = "active"
        found = await session.scalar(
            select(Enrollment).where(Enrollment.class_id == row.class_id, Enrollment.user_id == user.id)
        )
        if found is None:
            session.add(Enrollment(class_id=row.class_id, user_id=user.id, status="active"))
        else:
            found.status = "active"
    elif row.class_id is not None:
        user.role = "admin" if row.wanted_role == "admin" else "teacher"
        user.status = "active"
        link = await session.scalar(
            select(ClassTeacher).where(ClassTeacher.class_id == row.class_id, ClassTeacher.user_id == user.id)
        )
        if link is None:
            session.add(ClassTeacher(class_id=row.class_id, user_id=user.id))
        if seat is not None:
            seat.user_id = user.id
    await session.flush()


async def approve(
    session: AsyncSession, admin: User, target_id: int
) -> tuple[str, tuple[tuple[str, str], ...]]:
    if not await is_school_admin(session, admin):
        return ("Принимать заявки может администратор школы.", ())
    row = await session.get(JoinApplication, target_id)
    if row is None or row.status != "pending" or row.class_id is None:
        return ("Этой заявки уже нет.", ())
    target = await session.get(User, target_id)
    if target is None:
        return ("Человека уже нет.", ())
    seat = None
    if row.seat_code:
        seat = await session.scalar(
            select(StaffSeat).where(StaffSeat.class_id == row.class_id, StaffSeat.code == row.seat_code)
        )
        if seat is not None and seat.user_id not in {None, target.id}:
            return ("Место уже занято.", ())
    await _activate(session, target, row, seat)
    return (f"Принял {target.display_name}.", await pending_buttons(session, admin))


async def pending_buttons(session: AsyncSession, admin: User) -> tuple[tuple[str, str], ...]:
    seat = await session.scalar(
        select(StaffSeat).where(StaffSeat.user_id == admin.id, StaffSeat.code == "admin")
    )
    if seat is None:
        return ()
    rows = list(
        await session.scalars(
            select(JoinApplication).where(
                JoinApplication.school_id == seat.school_id,
                JoinApplication.status == "pending",
            )
        )
    )
    buttons = []
    for row in rows[:10]:
        person = await session.get(User, row.user_id)
        label = (person.display_name if person else "Заявка")[:80]
        buttons.append((f"Принять {label}", f"approve:{row.user_id}"))
    return tuple(buttons)


async def pending_reply(session: AsyncSession, admin: User) -> tuple[str, tuple[tuple[str, str], ...]]:
    buttons = await pending_buttons(session, admin)
    if not buttons:
        return ("Заявок нет.", ())
    return ("Кто просится в Школу 16, класс 5А.", buttons)
