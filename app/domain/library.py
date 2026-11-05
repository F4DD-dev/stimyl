"""Хранилище материалов класса и поиск фрагментов по теме."""

import re
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Enrollment, Material, MaterialChunk
from app.domain.materials import chunk_text

_WORD = re.compile(r"[0-9a-zа-яё]{3,}", re.IGNORECASE)
_STOP = {
    "как", "что", "это", "для", "или", "при", "так", "вот", "где", "когда", "чем", "надо",
    "нужно", "можно", "тема", "задание", "задача", "решить", "реши", "найди", "помоги",
    "объясни", "понимаю", "проверить", "умение", "через", "тест", "работа", "работу",
}


async def save_material(
    session: AsyncSession,
    *,
    class_id: int,
    author_id: int,
    title: str,
    kind: str,
    text: str,
) -> Material:
    material = Material(
        class_id=class_id,
        author_id=author_id,
        title=title.strip()[:200] or "Материал",
        kind=kind[:16],
        chars=len(text),
        created_at=datetime.now(UTC),
    )
    session.add(material)
    await session.flush()
    for position, piece in enumerate(chunk_text(text), start=1):
        session.add(
            MaterialChunk(
                material_id=material.id, class_id=class_id, position=position, text=piece
            )
        )
    await session.flush()
    return material


async def list_materials(session: AsyncSession, class_id: int) -> list[dict]:
    rows = (
        await session.execute(
            select(Material, func.count(MaterialChunk.id))
            .outerjoin(MaterialChunk, MaterialChunk.material_id == Material.id)
            .where(Material.class_id == class_id)
            .group_by(Material.id)
            .order_by(Material.id.desc())
        )
    ).all()
    return [
        {
            "id": material.id,
            "title": material.title,
            "kind": material.kind,
            "chars": material.chars,
            "fragments": int(count),
            "created_at": material.created_at.isoformat(),
        }
        for material, count in rows
    ]


async def delete_material(session: AsyncSession, class_id: int, material_id: int) -> bool:
    material = await session.get(Material, material_id)
    if material is None or material.class_id != class_id:
        return False
    await session.execute(delete(MaterialChunk).where(MaterialChunk.material_id == material.id))
    await session.delete(material)
    await session.flush()
    return True


async def has_materials(session: AsyncSession, class_id: int | None) -> bool:
    if class_id is None:
        return False
    found = await session.scalar(
        select(MaterialChunk.id).where(MaterialChunk.class_id == class_id).limit(1)
    )
    return found is not None


def search_terms(text: str) -> list[str]:
    words = []
    for word in _WORD.findall(text.casefold().replace("ё", "е")):
        if word in _STOP or word in words:
            continue
        words.append(word)
    return words[:24]


async def find_fragments(
    session: AsyncSession, class_id: int | None, query: str, limit: int = 4
) -> list[str]:
    """Фрагменты класса, где встречаются слова запроса. Ничего не нашлось — пустой список."""
    terms = search_terms(query)
    if class_id is None or not terms:
        return []
    vector = func.to_tsvector("russian", MaterialChunk.text)
    tsquery = func.to_tsquery("russian", " | ".join(terms))
    rank = func.ts_rank(vector, tsquery)
    rows = await session.scalars(
        select(MaterialChunk.text)
        .where(MaterialChunk.class_id == class_id, vector.op("@@")(tsquery))
        .order_by(rank.desc(), MaterialChunk.id)
        .limit(limit)
    )
    return list(rows)


async def class_of_student(session: AsyncSession, user_id: int) -> int | None:
    return await session.scalar(
        select(Enrollment.class_id)
        .where(Enrollment.user_id == user_id, Enrollment.status == "active")
        .order_by(Enrollment.class_id)
        .limit(1)
    )
