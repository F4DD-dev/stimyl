import random

from app.domain.curriculum import classify_topic, topic_by_title
from app.domain.tasks import generate_task


def build_check_draft(
    topic: str,
    goal: str,
    count: int,
    difficulty: str,
    audience: str,
    students: list[str],
) -> dict | None:
    """Questions from the grade-8 bank. Nothing is stored or sent to students."""
    material = topic_by_title(topic)
    if material is None:
        return None
    order = list(material.tasks)
    if difficulty == "hard":
        order.reverse()
    items = []
    for index in range(count):
        task = order[index % len(order)]
        items.append(
            {
                "number": index + 1,
                "prompt": task.prompt,
                "choices": [],
                "reference": task.answer,
                "hint": task.hint,
            }
        )
    note = None
    if count > len(order):
        note = (
            "В банке темы меньше разных заданий, чем вы просите. "
            "Повторные пункты — те же задачи, не новый текст."
        )
    return {
        "topic": material.title,
        "goal": goal.strip(),
        "count": count,
        "difficulty": difficulty,
        "audience": audience,
        "students": list(students),
        "items": items,
        "source": "bank",
        "persisted": False,
        "note": note,
    }


def build_stimul_draft(
    topic: str,
    goal: str,
    count: int,
    difficulty: str,
    audience: str,
    students: list[str],
) -> dict | None:
    """Questions with answers the code can check. Unknown subjects are refused."""
    title = topic.strip()
    if not title:
        return None
    material = topic_by_title(title)
    family = material.title if material is not None else None
    if family is None:
        guess = classify_topic(f"{title} {goal}")
        if guess.confident and guess.title:
            family = guess.title
    if family is None:
        return None
    level = "hard" if difficulty == "hard" else "easy"
    rng = random.Random()
    items = []
    used: set[str] = set()
    for index in range(count):
        task = generate_task(family, level, rng, used)
        used.add(task.prompt)
        items.append(
            {
                "number": index + 1,
                "prompt": task.prompt,
                "choices": [],
                "reference": task.answer,
                "hint": task.hint,
            }
        )
    note = f"Вопросы по теме «{family}» из программы 8 класса. Ответы уже посчитаны, их можно поправить."
    if family != title:
        note = (
            f"Тема «{title}» похожа на «{family}» из программы 8 класса. "
            "Вопросы взяты оттуда, ответы посчитаны. Перед отправкой их можно поправить."
        )
    return {
        "topic": title,
        "goal": goal.strip(),
        "count": count,
        "difficulty": difficulty,
        "audience": audience,
        "students": list(students),
        "items": items,
        "source": "stimul",
        "persisted": False,
        "note": note,
    }
