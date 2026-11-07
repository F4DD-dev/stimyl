"""Что предлагает модель и что из этого пропускает код. Модель не судья ответа."""

import re
from dataclasses import dataclass, field
from fractions import Fraction

from app.domain.answers import answers_match, parse_answer
from app.domain.curriculum import fold_text


@dataclass(frozen=True)
class TaskDraft:
    prompt: str
    answer: str
    hint: str = ""
    first_step: str = ""


@dataclass(frozen=True)
class LessonDraft:
    topic: str | None
    explanation: str
    example: str
    task: TaskDraft | None
    original_answer: str = ""
    off_topic: bool = False
    unreadable: bool = False
    direct_answer: str = ""


@dataclass(frozen=True)
class TeacherAsk:
    intent: str
    topic: str = ""
    goal: str = ""
    count: int = 3
    difficulty: str = "normal"
    students: tuple[str, ...] = field(default_factory=tuple)
    use_material: bool = False
    reply: str = ""


_LATEX = (
    (r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"\1/\2"),
    (r"\\sqrt\{([^{}]+)\}", r"√\1"),
    (r"\\cdot", "·"),
    (r"\\times", "×"),
    (r"\\pm", "±"),
    (r"\\leq?", "≤"),
    (r"\\geq?", "≥"),
    (r"\\neq?", "≠"),
    (r"\\div", ":"),
    (r"\^\{?2\}?", "²"),
    (r"\^\{?3\}?", "³"),
    (r"\\[()\[\]]", ""),
    (r"\$", ""),
    (r"\\text\{([^{}]*)\}", r"\1"),
)
_RESULT_MARK = re.compile(r"(=|ответ|получ|равн|корн|итог|выйдет|будет)", re.IGNORECASE)
_NUMBER = re.compile(r"(?<![\w/.,])[-−]?\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?(?![\w/])")


def plain(text: str | None, limit: int = 1200) -> str:
    """Текст для чата MAX: без markdown и LaTeX, без пустых строк подряд."""
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n")
    for pattern, target in _LATEX:
        cleaned = re.sub(pattern, target, cleaned)
    cleaned = re.sub(r"\*\*|__|`", "", cleaned)
    cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", cleaned)
    cleaned = re.sub(r"(?m)^\s*[-*•]\s+", "", cleaned)
    cleaned = re.sub(r"(?<!\w)\*(\S[^*]*?)\*(?!\w)", r"\1", cleaned)
    cleaned = re.sub(r"(?<=[\w)²³])\s*\*\s*(?=[\w(√])", " · ", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if len(cleaned) > limit:
        cut = cleaned[:limit]
        stop = max(cut.rfind(". "), cut.rfind("\n"))
        cleaned = cut[: stop + 1].strip() if stop > limit // 2 else cut.rstrip() + "…"
    return cleaned


def _value(token: str) -> Fraction | None:
    parsed = parse_answer(token.replace(" ", ""))
    return parsed.values[0] if len(parsed.values) == 1 else None


def leaks(text: str, answer: str) -> bool:
    """Все значения ответа названы как итог: после «=», «ответ», «получится» и похожих слов.
    Один совпавший корень в похожем примере сливом не считается."""
    goals = set(parse_answer(answer or "").values)
    if not text or not goals:
        return False
    named: set[Fraction] = set()
    for match in _NUMBER.finditer(text):
        value = _value(match.group(0).replace("−", "-"))
        if value is None or value not in goals:
            continue
        before = text[max(0, match.start() - 18) : match.start()]
        if _RESULT_MARK.search(before):
            named.add(value)
    return named == goals


def mentions(text: str, answer: str) -> bool:
    """Строже, чем leaks: значение эталона встречается в тексте хоть где-то."""
    goals = set(parse_answer(answer or "").values)
    if not text or not goals:
        return False
    for match in _NUMBER.finditer(text):
        if _value(match.group(0).replace("−", "-")) in goals:
            return True
    return False


def same_problem(task: TaskDraft | None, original_answer: str) -> bool:
    """Задание с тем же ответом, что у задачи ученика, — это его задача, а не похожая."""
    if task is None or not usable_answer(original_answer):
        return False
    return answers_match(original_answer, task.answer)


def usable_answer(answer: str) -> bool:
    values = parse_answer(answer or "").values
    return 0 < len(values) <= 4


def task_confirmed(task: TaskDraft | None, solved: str | None) -> bool:
    """Эталон модели принимается, только если второе независимое решение дало то же число."""
    if task is None or not task.prompt.strip() or not usable_answer(task.answer):
        return False
    return bool(solved) and answers_match(task.answer, solved or "")


def match_topic(name: str | None, titles: list[str]) -> str | None:
    if not name:
        return None
    wanted = fold_text(name).strip(" .«»\"")
    if not wanted or wanted in {"null", "none", "нет"}:
        return None
    for title in titles:
        if fold_text(title) == wanted:
            return title
    for title in titles:
        folded = fold_text(title)
        if wanted in folded or folded in wanted:
            return title
    return None


def match_students(
    names: list[str] | tuple[str, ...], roster: list[tuple[int, str]]
) -> tuple[list[int], list[str], list[str]]:
    """Имена из запроса учителя к ученикам класса. Неоднозначное имя не угадываем."""
    ids: list[int] = []
    found: list[str] = []
    unknown: list[str] = []
    for raw in names:
        wanted = fold_text(raw).strip()
        if not wanted:
            continue
        exact = [(uid, name) for uid, name in roster if fold_text(name) == wanted]
        loose = exact or [
            (uid, name)
            for uid, name in roster
            if any(part.startswith(wanted[:4]) for part in fold_text(name).split())
            and len(wanted) >= 3
        ]
        if len(loose) == 1 and loose[0][0] not in ids:
            ids.append(loose[0][0])
            found.append(loose[0][1])
        elif len(loose) != 1:
            unknown.append(raw.strip())
    return ids, found, unknown
