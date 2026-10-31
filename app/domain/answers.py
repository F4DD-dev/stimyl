"""Сравнение ответа ученика с числом задания. Без eval."""

import re
from dataclasses import dataclass
from fractions import Fraction

_NOT_ATTEMPT = {"не знаю", "?", "подскажи"}
_UNICODE_FRACTIONS = {
    "½": "1/2",
    "⅓": "1/3",
    "⅔": "2/3",
    "¼": "1/4",
    "¾": "3/4",
    "⅕": "1/5",
    "⅖": "2/5",
    "⅗": "3/5",
    "⅘": "4/5",
    "⅙": "1/6",
    "⅚": "5/6",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}
_TOLERANCE = Fraction(1, 1000)


@dataclass(frozen=True)
class ParsedAnswer:
    attempt: bool
    values: tuple[Fraction, ...]
    decimal: bool


def is_attempt(text: str) -> bool:
    return parse_answer(text).attempt


def parse_answer(text: str) -> ParsedAnswer:
    folded = text.casefold().replace("ё", "е")
    compact = re.sub(r"\s+", " ", folded).strip()
    if compact in _NOT_ATTEMPT or compact.rstrip(".!") in _NOT_ATTEMPT:
        return ParsedAnswer(False, (), False)
    normalized = folded.replace("−", "-").replace("–", "-").replace("—", "-")
    for source, target in _UNICODE_FRACTIONS.items():
        normalized = normalized.replace(source, target)
    values: list[Fraction] = []
    decimal = False
    for part in _parts(normalized):
        parsed = _number(_clean(part))
        if parsed is None:
            continue
        value, used_decimal = parsed
        values.append(value)
        decimal = decimal or used_decimal
    return ParsedAnswer(True, tuple(values), decimal)


def answers_match(expected: str, given: str) -> bool:
    left = parse_answer(expected)
    right = parse_answer(given)
    if not right.attempt or not left.values or len(left.values) != len(right.values):
        return False
    pairs = zip(sorted(left.values), sorted(right.values), strict=True)
    return all(_close(goal, got, right.decimal) for goal, got in pairs)


def _close(goal: Fraction, got: Fraction, decimal: bool) -> bool:
    if goal == got:
        return True
    return decimal and abs(goal - got) <= _TOLERANCE


def _parts(text: str) -> list[str]:
    if re.search(r"\d\s*и\s*\d|;", text):
        return [item for item in re.split(r"\s*и\s*|;", text) if item.strip()]
    return [text]


def _clean(token: str) -> str:
    token = token.strip().rstrip(".")
    token = re.sub(r"^(ответ|d|x\d*|х\d*)\s*[:=]?\s*", "", token)
    token = re.sub(r"(см|мм|дм|км|кг|г|м)\.?$", "", token.strip())
    token = re.sub(r"(?<=\d)\s(?=\d{3}(?:\D|$))", "", token)
    return token.replace(" ", "")


def _number(token: str) -> tuple[Fraction, bool] | None:
    if not token:
        return None
    decimal = "," in token or "." in token
    token = token.replace(",", ".")
    if "/" in token:
        numerator, _, denominator = token.partition("/")
        if not _integer(numerator) or not _integer(denominator) or denominator in {"0", "-0"}:
            return None
        return Fraction(int(numerator), int(denominator)), False
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", token):
        return None
    return Fraction(token), decimal


def _integer(token: str) -> bool:
    return bool(re.fullmatch(r"[+-]?\d+", token))
