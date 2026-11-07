"""Локальная консоль базы. Запуск из корня: python -m app.desk"""

import asyncio
import getpass
import os
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.config import Settings, get_settings
from app.db.models import AuditLog, User
from app.db.session import make_engine, make_session_factory
from app.domain.accounts import (
    add_class,
    add_school,
    close_user,
    delete_user_data,
    set_blocked,
)
from app.domain.onboarding import accept_claim, active_managers, reject_claim
from app.domain.operator import (
    id_hint,
    link_subject,
    people_text,
    place_student,
    place_teacher,
    schools_text,
)
from app.domain.school_admin import (
    class_status,
    grant_school_manager,
    pending_claims_text,
    transfer_school_manager,
)

TIMEWEB_HOST = os.environ.get("TIMEWEB_DB_HOST", "")
TIMEWEB = (
    "postgresql+asyncpg://stimul:{password}@" + TIMEWEB_HOST + ":5432/stimul?ssl=require"
    if TIMEWEB_HOST
    else ""
)
PASSWORD_FILE = Path(".local/db-password.txt")
MENU = """
1 Люди
2 Школы, классы, предметы
3 Сводка класса
4 Заявки
5 Принять заявку
6 Отклонить заявку
7 Сделать учеником
8 Сделать учителем
9 Назначить предмет
10 Назначить ответственного
11 Передать управление
12 Новая школа
13 Новый класс
14 Заблокировать
15 Разблокировать
16 Скрыть человека
17 Удалить человека
18 Журнал
0 Выход
"""


def main() -> None:
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\nВыход.")


async def _main() -> None:
    settings = get_settings()
    url = _choose_url(settings)
    if url is None:
        return
    target = _target(url)
    print(f"Открываю {target}")
    engine = make_engine(url)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            await session.execute(select(1))
    except SQLAlchemyError as exc:
        print(f"База не открылась: {exc.__class__.__name__}. Пароль и адрес в текст ошибки не входят.")
        await engine.dispose()
        return
    print(f"Подключено: {target}")
    print("Людей консоль не создаёт. Переписку и номера она не показывает.")
    writing = {"asked": False, "allowed": _local(url)}
    try:
        while True:
            print(MENU)
            choice = _ask("Номер: ")
            if choice in {"0", "q", "й"}:
                return
            try:
                async with factory() as session:
                    stay = await _command(session, settings, choice, target, writing)
                    if not stay:
                        return
            except IntegrityError:
                print("Такая школа или класс уже есть.")
            except SQLAlchemyError as exc:
                print(f"База ответила ошибкой: {exc.__class__.__name__}.")
    finally:
        await engine.dispose()


async def _command(session, settings: Settings, choice: str, target: str, writing: dict) -> bool:
    if choice == "1":
        print(await people_text(session))
        return True
    if choice == "2":
        print(await schools_text(session))
        return True
    if choice == "3":
        print(await class_status(session))
        return True
    if choice == "4":
        print(await pending_claims_text(session))
        return True
    if choice == "5":
        await _claim(session, target, writing, accept=True)
        return True
    if choice == "6":
        await _claim(session, target, writing, accept=False)
        return True
    if choice == "7":
        user_id = _number("Внутренний id человека: ")
        class_id = _optional_number("Id класса, пусто если без класса: ")
        if user_id is None or class_id is _MISSING or not _allow(target, writing):
            return True
        step = await place_student(session, user_id, class_id)
        print(step.text)
        await _finish(session, step.changed)
        return True
    if choice == "8":
        user_id = _number("Внутренний id человека: ")
        class_id = _optional_number("Id класса, пусто если без класса: ")
        if user_id is None or class_id is _MISSING or not _allow(target, writing):
            return True
        step = await place_teacher(session, user_id, class_id)
        print(step.text)
        await _finish(session, step.changed)
        return True
    if choice == "9":
        user_id = _number("Внутренний id учителя: ")
        class_id = _number("Id класса: ")
        subject_id = _number("Id предмета: ")
        if None in {user_id, class_id, subject_id} or not _allow(target, writing):
            return True
        step = await link_subject(session, user_id, class_id, subject_id)
        print(step.text)
        await _finish(session, step.changed)
        return True
    if choice == "10":
        max_id = _ask("Id MAX из колонки max: ")
        if not max_id.isdigit():
            print("Нужен числовой id MAX.")
            return True
        preview = await grant_school_manager(session, max_id, apply=False)
        print(preview.text)
        if preview.ok and _allow(target, writing) and _yes():
            result = await grant_school_manager(session, max_id, apply=True)
            print(result.text)
            await _finish(session, result.changed)
        return True
    if choice == "11":
        source = _ask("Id MAX, у кого забрать: ")
        target_max = _ask("Id MAX, кому отдать: ")
        preview = await transfer_school_manager(session, source, target_max, apply=False)
        print(preview.text)
        if preview.ok and _allow(target, writing) and _yes():
            result = await transfer_school_manager(session, source, target_max, apply=True)
            print(result.text)
            await _finish(session, result.changed)
        return True
    if choice == "12":
        title = _ask("Название школы: ")
        if not title or not _allow(target, writing):
            return True
        school = await add_school(session, title)
        print(f"Школа {school.id}: {school.title}")
        await _finish(session, True)
        return True
    if choice == "13":
        school_id = _number("Id школы: ")
        title = _ask("Название класса: ")
        if school_id is None or not title or not _allow(target, writing):
            return True
        created = await add_class(session, school_id, title)
        if created is None:
            print("Школа не найдена.")
            return True
        name = settings.bot_username or "<бот>"
        print(f"Класс {created.id}, код {created.join_code}, ключ {created.join_key}")
        print(f"https://max.ru/{name}?start={created.join_key}")
        await _finish(session, True)
        return True
    if choice == "14":
        await _user_flag(session, target, writing, blocked=True)
        return True
    if choice == "15":
        await _user_flag(session, target, writing, blocked=False)
        return True
    if choice == "16":
        user_id = await _person_id(session, "Первая колонка id, не max: ")
        if user_id is None or not _allow(target, writing) or not _yes("Скрыть человека?"):
            return True
        ok = await close_user(session, user_id, None)
        print("Скрыт." if ok else "Не найден или уже скрыт.")
        await _finish(session, ok)
        return True
    if choice == "17":
        user_id = await _person_id(session, "Первая колонка id, не max: ")
        if user_id is None or not _allow(target, writing):
            return True
        again = _number("Повтори этот же внутренний id. Удаление стирает ответы и вход: ")
        if again != user_id:
            print("Id не совпал. Ничего не удалено.")
            return True
        ok = await delete_user_data(session, user_id, None)
        print("Удалён." if ok else "Не найден.")
        await _finish(session, ok)
        return True
    if choice == "18":
        rows = list(await session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(30)))
        if not rows:
            print("Журнал пуст.")
            return True
        for row in rows:
            print(f"{row.created_at}\t{row.action}\tactor {row.actor_user_id}\ttarget {row.target_user_id}")
        return True
    print("Такого пункта нет.")
    return True


async def _claim(session, target: str, writing: dict, *, accept: bool) -> None:
    print(await pending_claims_text(session))
    user_id = _number("Внутренний id заявки: ")
    if user_id is None or not _allow(target, writing):
        return
    managers = await active_managers(session)
    if not managers:
        print("Ответственный не назначен. Сначала пункт 10.")
        return
    action = accept_claim if accept else reject_claim
    ok, detail = await action(session, managers[0], user_id)
    print(detail if ok else f"Не вышло: {detail}")
    await _finish(session, ok)


async def _person_id(session, prompt: str) -> int | None:
    user_id = _number(prompt)
    if user_id is None:
        return None
    hint = await id_hint(session, user_id)
    if hint is not None:
        print(hint)
        return None
    return user_id


async def _user_flag(session, target: str, writing: dict, *, blocked: bool) -> None:
    user_id = await _person_id(session, "Первая колонка id, не max: ")
    if user_id is None or not _allow(target, writing):
        return
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        print("Человек не найден или скрыт.")
        return
    verb = "Заблокировать" if blocked else "Разблокировать"
    if not _yes(f"{verb} {user.display_name}?"):
        return
    print("ok" if await set_blocked(session, user_id, blocked, None) else "не найден")
    await _finish(session, True)


async def _finish(session, changed: bool) -> None:
    if changed:
        await session.commit()
    else:
        await session.rollback()


def _choose_url(settings: Settings) -> str | None:
    current = (settings.database_url or "").strip()
    print("Куда подключиться?")
    if current:
        print(f"1 Адрес из окружения: {_target(current)}")
    else:
        print("1 В окружении DATABASE_URL пустой.")
    print(f"2 База Timeweb: stimul @ {TIMEWEB_HOST or 'задайте TIMEWEB_DB_HOST'}")
    choice = _ask("Номер: ")
    if choice == "1":
        if not current:
            print("Задай DATABASE_URL или выбери пункт 2.")
            return None
        return current
    if choice == "2":
        if not TIMEWEB:
            print("Задай TIMEWEB_DB_HOST в окружении.")
            return None
        password = _password()
        if not password:
            print("Пароль пустой.")
            return None
        return TIMEWEB.format(password=quote(password, safe=""))
    print("Нужен 1 или 2.")
    return None


def _password() -> str:
    if PASSWORD_FILE.is_file() and _yes(f"Взять пароль из {PASSWORD_FILE}?"):
        return PASSWORD_FILE.read_text(encoding="utf-8").strip()
    return getpass.getpass("Пароль пользователя stimul: ")


def _target(url: str) -> str:
    parsed = make_url(url)
    host = parsed.host or "локально"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.database or 'база'} @ {host}{port}, пользователь {parsed.username or '-'}"


def _local(url: str) -> bool:
    host = make_url(url).host or ""
    return host in {"localhost", "127.0.0.1", "::1", "db"}


def _allow(target: str, writing: dict) -> bool:
    if writing["allowed"]:
        return True
    if not writing["asked"]:
        writing["asked"] = True
        writing["allowed"] = _yes(f"Писать в {target}?")
    if not writing["allowed"]:
        print("Запись выключена. Смотреть можно.")
    return writing["allowed"]


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return "0"


def _yes(prompt: str = "Записать?") -> bool:
    return _ask(f"{prompt} Напиши да: ").lower() == "да"


def _number(prompt: str) -> int | None:
    raw = _ask(prompt)
    if not raw.isdigit():
        print("Нужно целое число.")
        return None
    return int(raw)


_MISSING = object()


def _optional_number(prompt: str) -> int | None | object:
    raw = _ask(prompt)
    if not raw:
        return None
    if not raw.isdigit():
        print("Нужно целое число или пустая строка.")
        return _MISSING
    return int(raw)


if __name__ == "__main__":
    main()
