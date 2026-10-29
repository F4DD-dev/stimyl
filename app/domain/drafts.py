from app.domain.curriculum import topic_by_title


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
