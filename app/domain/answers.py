from decimal import Decimal, InvalidOperation


def answers_match(expected: str, given: str) -> bool:
    left = _canon(expected)
    right = _canon(given)
    if not left or not right:
        return False
    if left == right:
        return True
    try:
        return abs(_to_decimal(left) - _to_decimal(right)) <= Decimal("0.001")
    except (InvalidOperation, ZeroDivisionError):
        return False


def _canon(value: str) -> str:
    text = value.strip().lower().replace(" ", "").replace(",", ".")
    text = text.replace("х", "x")
    for prefix in ("ответ:", "ответ", "x="):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text


def _to_decimal(text: str) -> Decimal:
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        return Decimal(numerator) / Decimal(denominator)
    return Decimal(text)
