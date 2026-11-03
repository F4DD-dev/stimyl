"""Минимальная админка в консоли. Роли из базы, не из аргументов клиента."""

import argparse
import asyncio

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import AuditLog, AuthIdentity, School, SchoolClass, User
from app.db.session import make_engine, make_session_factory
from app.domain.accounts import (
    add_class,
    add_school,
    approve_teacher,
    close_user,
    create_invite,
    create_transfer,
    delete_user_data,
    set_blocked,
)
from app.domain.school_admin import (
    class_status,
    grant_school_manager,
    pending_claims_text,
    transfer_school_manager,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.admin")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("users")
    sub.add_parser("schools")
    sub.add_parser("audit")
    approve = sub.add_parser("approve")
    approve.add_argument("user_id", type=int)
    block = sub.add_parser("block")
    block.add_argument("user_id", type=int)
    unblock = sub.add_parser("unblock")
    unblock.add_argument("user_id", type=int)
    close = sub.add_parser("close")
    close.add_argument("user_id", type=int)
    delete = sub.add_parser("delete")
    delete.add_argument("user_id", type=int)
    delete.add_argument("--yes", action="store_true")
    sub.add_parser("invite")
    transfer = sub.add_parser("transfer")
    transfer.add_argument("user_id", type=int)
    school = sub.add_parser("add-school")
    school.add_argument("title")
    school_class = sub.add_parser("add-class")
    school_class.add_argument("school_id", type=int)
    school_class.add_argument("title")
    grant = sub.add_parser("grant-school-manager")
    grant.add_argument("max_id")
    grant.add_argument("--yes", action="store_true")
    transfer = sub.add_parser("transfer-school-manager")
    transfer.add_argument("source_max")
    transfer.add_argument("target_max")
    transfer.add_argument("--yes", action="store_true")
    sub.add_parser("class")
    sub.add_parser("claims")
    asyncio.run(_run(parser.parse_args()))


async def _run(args: argparse.Namespace) -> None:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("Нужна DATABASE_URL")
    if settings.session_secret == "change-me":
        print("SESSION_SECRET всё ещё change-me. Для боя замени его.")
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            changed = await _command(session, args, settings)
            if changed:
                await session.commit()
            else:
                await session.rollback()
    finally:
        await engine.dispose()


async def _command(session, args, settings) -> bool:
    if args.cmd == "users":
        rows = await session.execute(
            select(User, AuthIdentity.external_id)
            .join(AuthIdentity, AuthIdentity.user_id == User.id)
            .where(AuthIdentity.provider == "max", AuthIdentity.revoked_at.is_(None))
            .order_by(User.id)
        )
        print("id\trole\tstatus\tmanage\tmax\tname")
        for user, external_id in rows.all():
            closed = " closed" if user.deleted_at is not None else ""
            manage = "да" if user.can_manage_school else "нет"
            print(
                f"{user.id}\t{user.role}\t{user.status}{closed}\t{manage}\t{external_id}\t{user.display_name}"
            )
        return False
    if args.cmd == "schools":
        schools = list(await session.scalars(select(School).order_by(School.id)))
        classes = list(await session.scalars(select(SchoolClass).order_by(SchoolClass.id)))
        for school in schools:
            print(f"school {school.id}\t{school.title}")
            for item in classes:
                if item.school_id == school.id:
                    print(f"  class {item.id}\t{item.title}\tkey {item.join_key}\tcode {item.join_code}")
        return False
    if args.cmd == "audit":
        rows = list(
            await session.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(50))
        )
        for row in rows:
            print(f"{row.created_at}\t{row.action}\tactor {row.actor_user_id}\ttarget {row.target_user_id}")
        return False
    if args.cmd == "claims":
        print(await pending_claims_text(session))
        return False
    if args.cmd == "class":
        print(await class_status(session))
        return False
    if args.cmd == "grant-school-manager":
        result = await grant_school_manager(session, args.max_id, apply=args.yes)
        print(result.text)
        if not result.ok:
            raise SystemExit(1)
        return result.changed
    if args.cmd == "transfer-school-manager":
        result = await transfer_school_manager(
            session, args.source_max, args.target_max, apply=args.yes
        )
        print(result.text)
        if not result.ok:
            raise SystemExit(1)
        return result.changed
    if args.cmd == "approve":
        print("ok" if await approve_teacher(session, args.user_id, None) else "не найден")
        return True
    if args.cmd == "block":
        print("ok" if await set_blocked(session, args.user_id, True, None) else "не найден")
        return True
    if args.cmd == "unblock":
        print("ok" if await set_blocked(session, args.user_id, False, None) else "не найден")
        return True
    if args.cmd == "close":
        print("ok" if await close_user(session, args.user_id, None) else "не найден")
        return True
    if args.cmd == "delete":
        if not args.yes:
            raise SystemExit("Добавь --yes. Удаление стирает ответы и вход.")
        print("ok" if await delete_user_data(session, args.user_id, None) else "не найден")
        return True
    if args.cmd == "invite":
        print(await create_invite(session, None, settings))
        return True
    if args.cmd == "transfer":
        code = await create_transfer(session, args.user_id, None, settings)
        print(code or "не найден")
        return True
    if args.cmd == "add-school":
        school = await add_school(session, args.title)
        print(school.id)
        return True
    if args.cmd == "add-class":
        created = await add_class(session, args.school_id, args.title)
        if created is None:
            print("школа не найдена")
            return False
        name = settings.bot_username or "<бот>"
        print(f"key {created.join_key}")
        print(f"code {created.join_code}")
        print(f"https://max.ru/{name}?start={created.join_key}")
        return True
    return False
