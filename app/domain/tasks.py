"""Задания из шаблонов. Числа случайные, ответ считает Fraction, без eval."""

import random
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class GeneratedTask:
    prompt: str
    answer: str
    hint: str
    level: str
    first_step: str = ""


def _fmt(value: Fraction) -> str:
    number = Fraction(value)
    if number.denominator == 1:
        return str(number.numerator)
    return f"{number.numerator}/{number.denominator}"


def _frac(rng: random.Random, level: str) -> Fraction:
    high = 9 if level == "hard" else 5
    denominator = rng.randint(2, high)
    numerator = rng.randint(1, denominator - 1)
    return Fraction(numerator, denominator)


def _pair(rng: random.Random, level: str) -> tuple[int, int]:
    high = 12 if level == "hard" else 6
    return rng.randint(2, high), rng.randint(2, high)


def _signed(name: str, value: int) -> str:
    if value < 0:
        return f"- {abs(value)}{name}"
    if value > 0:
        return f"+ {value}{name}"
    return ""


def _quad(b: int, c: int) -> str:
    return f"x² {_signed('x', b)} {_signed('', c)} = 0".replace("  ", " ")


def _add(rng: random.Random, level: str) -> GeneratedTask:
    left, right = _frac(rng, level), _frac(rng, level)
    return GeneratedTask(
        f"Сложи {_fmt(left)} и {_fmt(right)}. Напиши результат дробью.",
        _fmt(left + right),
        "Приведи к общему знаменателю и сложи числители.",
        level,
    )


def _sub(rng: random.Random, level: str) -> GeneratedTask:
    left, right = _frac(rng, level), _frac(rng, level)
    return GeneratedTask(
        f"Вычти {_fmt(right)} из {_fmt(left)}. Напиши результат дробью.",
        _fmt(left - right),
        "Приведи к общему знаменателю и вычти числители.",
        level,
    )


def _mul(rng: random.Random, level: str) -> GeneratedTask:
    left, right = _frac(rng, level), _frac(rng, level)
    return GeneratedTask(
        f"Умножь {_fmt(left)} на {_fmt(right)}. Напиши результат дробью.",
        _fmt(left * right),
        "Перемножь числители и знаменатели, затем сократи.",
        level,
    )


def _div(rng: random.Random, level: str) -> GeneratedTask:
    left, right = _frac(rng, level), _frac(rng, level)
    return GeneratedTask(
        f"Раздели {_fmt(left)} на {_fmt(right)}. Напиши результат дробью.",
        _fmt(left / right),
        "Умножь на дробь, перевёрнутую вверх дном, затем сократи.",
        level,
    )


def _simplify(rng: random.Random, level: str) -> GeneratedTask:
    factor = rng.randint(2, 6 if level == "hard" else 3)
    base = _frac(rng, level)
    return GeneratedTask(
        f"Сократи {base.numerator * factor}/{base.denominator * factor}. Напиши результат дробью.",
        _fmt(base),
        "Раздели числитель и знаменатель на общий множитель.",
        level,
    )


def _mixed(rng: random.Random, level: str) -> GeneratedTask:
    whole = rng.randint(1, 8 if level == "hard" else 3)
    part = _frac(rng, level)
    return GeneratedTask(
        f"Запиши {whole} + {_fmt(part)} одной дробью.",
        _fmt(Fraction(whole) + part),
        "Переведи целое в дробь с тем же знаменателем и сложи.",
        level,
    )


def _ax(rng: random.Random, level: str) -> GeneratedTask:
    factor, unknown = _pair(rng, level)
    return GeneratedTask(
        f"Реши {factor}x = {factor * unknown}. Напиши число x.",
        str(unknown),
        "Раздели обе части на число перед x.",
        level,
    )


def _plus(rng: random.Random, level: str) -> GeneratedTask:
    high = 20 if level == "hard" else 9
    unknown = rng.randint(1, high)
    shift = rng.randint(1, high)
    return GeneratedTask(
        f"Реши x + {shift} = {unknown + shift}. Напиши число x.",
        str(unknown),
        "Перенеси число в другую часть и поменяй знак.",
        level,
    )


def _minus(rng: random.Random, level: str) -> GeneratedTask:
    high = 20 if level == "hard" else 9
    unknown = rng.randint(2, high)
    shift = rng.randint(1, unknown - 1)
    return GeneratedTask(
        f"Реши x - {shift} = {unknown - shift}. Напиши число x.",
        str(unknown),
        "Перенеси число в другую часть и поменяй знак.",
        level,
    )


def _ax_plus(rng: random.Random, level: str) -> GeneratedTask:
    factor, unknown = _pair(rng, level)
    shift = rng.randint(1, 9 if level == "hard" else 4)
    left = factor * unknown + shift
    return GeneratedTask(
        f"Реши {factor}x + {shift} = {left}. Напиши число x.",
        str(unknown),
        "Сначала перенеси свободное число, потом раздели на число перед x.",
        level,
    )


def _ax_minus(rng: random.Random, level: str) -> GeneratedTask:
    factor, unknown = _pair(rng, level)
    shift = rng.randint(1, 9 if level == "hard" else 4)
    left = factor * unknown - shift
    return GeneratedTask(
        f"Реши {factor}x - {shift} = {left}. Напиши число x.",
        str(unknown),
        "Сначала перенеси свободное число, потом раздели на число перед x.",
        level,
    )


def _x_over(rng: random.Random, level: str) -> GeneratedTask:
    denominator = rng.randint(2, 8 if level == "hard" else 4)
    unknown = rng.randint(1, 9 if level == "hard" else 5)
    return GeneratedTask(
        f"Реши x/{denominator} = {unknown}. Напиши число x.",
        str(denominator * unknown),
        "Умножь обе части на знаменатель.",
        level,
    )


def _discriminant(rng: random.Random, level: str) -> GeneratedTask:
    coefficient = rng.randint(1, 12 if level == "hard" else 6)
    free = rng.randint(-5, 6 if level == "hard" else 4)
    value = coefficient * coefficient - 4 * free
    return GeneratedTask(
        f"Найди D для {_quad(coefficient, free)}. Напиши число.",
        str(value),
        "Подставь коэффициенты в формулу дискриминанта.",
        level,
    )


def _discriminant_a(rng: random.Random, level: str) -> GeneratedTask:
    leading = rng.randint(2, 4 if level == "hard" else 3)
    coefficient = rng.randint(1, 8 if level == "hard" else 5)
    free = rng.randint(-3, 4)
    value = coefficient * coefficient - 4 * leading * free
    body = f"{leading}x² {_signed('x', coefficient)} {_signed('', free)} = 0"
    return GeneratedTask(
        f"Найди D для {body}. Напиши число.",
        str(value),
        "В формуле дискриминанта не забудь коэффициент перед x².",
        level,
    )


def _roots(rng: random.Random, level: str) -> tuple[int, int, str]:
    high = 9 if level == "hard" else 5
    first = rng.randint(1, high)
    second = rng.randint(1, high)
    equation = _quad(-(first + second), first * second)
    return first, second, equation


def _larger_root(rng: random.Random, level: str) -> GeneratedTask:
    first, second, equation = _roots(rng, level)
    return GeneratedTask(
        f"Найди больший корень {equation}. Напиши число.",
        str(max(first, second)),
        "Разложи на множители или посчитай дискриминант и формулу корней.",
        level,
    )


def _smaller_root(rng: random.Random, level: str) -> GeneratedTask:
    first, second, equation = _roots(rng, level)
    return GeneratedTask(
        f"Найди меньший корень {equation}. Напиши число.",
        str(min(first, second)),
        "Разложи на множители или посчитай дискриминант и формулу корней.",
        level,
    )


def _sum_roots(rng: random.Random, level: str) -> GeneratedTask:
    first, second, equation = _roots(rng, level)
    return GeneratedTask(
        f"Найди сумму корней {equation}. Напиши число.",
        str(first + second),
        "У уравнения x² + bx + c = 0 сумма корней равна числу перед x с обратным знаком.",
        level,
    )


def _product_roots(rng: random.Random, level: str) -> GeneratedTask:
    first, second, equation = _roots(rng, level)
    return GeneratedTask(
        f"Найди произведение корней {equation}. Напиши число.",
        str(first * second),
        "У уравнения x² + bx + c = 0 произведение корней равно свободному члену.",
        level,
    )


_TRIPLES = (
    (3, 4, 5),
    (5, 12, 13),
    (6, 8, 10),
    (8, 15, 17),
    (7, 24, 25),
    (9, 40, 41),
    (12, 16, 20),
    (9, 12, 15),
)


def _triple(rng: random.Random, level: str) -> tuple[int, int, int]:
    pool = _TRIPLES if level == "hard" else _TRIPLES[:4]
    return rng.choice(pool)


def _hypotenuse(rng: random.Random, level: str) -> GeneratedTask:
    left, right, hyp = _triple(rng, level)
    return GeneratedTask(
        f"Катеты {left} и {right}. Чему равна гипотенуза?",
        str(hyp),
        "Сложи квадраты катетов и извлеки корень.",
        level,
    )


def _leg(rng: random.Random, level: str) -> GeneratedTask:
    left, right, hyp = _triple(rng, level)
    return GeneratedTask(
        f"Гипотенуза {hyp}, один катет {left}. Чему равен второй катет?",
        str(right),
        "Вычти квадрат известного катета из квадрата гипотенузы и извлеки корень.",
        level,
    )


def _square_area(rng: random.Random, level: str) -> GeneratedTask:
    side = rng.randint(4, 15) if level == "hard" else rng.randint(2, 8)
    return GeneratedTask(
        f"Сторона квадрата {side}. Чему равна площадь?",
        str(side * side),
        "Площадь квадрата равна стороне, умноженной на себя.",
        level,
    )


def _square_side(rng: random.Random, level: str) -> GeneratedTask:
    side = rng.randint(4, 12) if level == "hard" else rng.randint(2, 8)
    return GeneratedTask(
        f"Площадь квадрата {side * side}. Чему равна сторона?",
        str(side),
        "Подбери число, которое в квадрате даёт площадь.",
        level,
    )


def _square_perimeter(rng: random.Random, level: str) -> GeneratedTask:
    side = rng.randint(4, 15) if level == "hard" else rng.randint(2, 8)
    return GeneratedTask(
        f"Сторона квадрата {side}. Чему равен периметр?",
        str(side * 4),
        "У квадрата четыре равные стороны.",
        level,
    )


def _scaled_hyp(rng: random.Random, level: str) -> GeneratedTask:
    left, right, hyp = _triple(rng, "easy")
    scale = rng.randint(2, 5 if level == "hard" else 3)
    return GeneratedTask(
        f"Катеты {left * scale} и {right * scale}. Чему равна гипотенуза?",
        str(hyp * scale),
        "Сложи квадраты катетов и извлеки корень.",
        level,
    )


TEMPLATES: dict[str, tuple] = {
    "Дроби": (_add, _sub, _mul, _div, _simplify, _mixed),
    "Линейные уравнения": (_ax, _plus, _minus, _ax_plus, _ax_minus, _x_over),
    "Квадратные уравнения и дискриминант": (
        _discriminant,
        _discriminant_a,
        _larger_root,
        _smaller_root,
        _sum_roots,
        _product_roots,
    ),
    "Геометрия": (
        _hypotenuse,
        _leg,
        _square_area,
        _square_side,
        _square_perimeter,
        _scaled_hyp,
    ),
}


_STEPS = {
    _add: "Найди общий знаменатель двух дробей.",
    _sub: "Найди общий знаменатель двух дробей.",
    _mul: "Перемножь числители отдельно и знаменатели отдельно.",
    _div: "Переверни вторую дробь и умножь.",
    _simplify: "Найди число, на которое делятся и числитель, и знаменатель.",
    _mixed: "Переведи целое в дробь с тем же знаменателем.",
    _ax: "Раздели обе части на число перед x.",
    _plus: "Перенеси число без x в другую часть.",
    _minus: "Перенеси число без x в другую часть.",
    _ax_plus: "Сначала убери свободное число из левой части.",
    _ax_minus: "Сначала убери свободное число из левой части.",
    _x_over: "Умножь обе части на знаменатель.",
    _discriminant: "Выпиши a, b и c.",
    _discriminant_a: "Выпиши a, b и c.",
    _larger_root: "Посчитай дискриминант.",
    _smaller_root: "Посчитай дискриминант.",
    _sum_roots: "Посмотри на число перед x.",
    _product_roots: "Посмотри на свободный член.",
    _hypotenuse: "Возведи катеты в квадрат и сложи.",
    _leg: "Возведи гипотенузу и известный катет в квадрат.",
    _square_area: "Умножь сторону на себя.",
    _square_side: "Подбери число, квадрат которого равен площади.",
    _square_perimeter: "Умножь сторону на четыре.",
    _scaled_hyp: "Возведи катеты в квадрат и сложи.",
}


FRESH_TRIES = 10


def generate_task(
    title: str,
    level: str,
    rng: random.Random,
    exclude: set[str] | frozenset[str] | None = None,
) -> GeneratedTask:
    """Задание, которого нет в exclude. Пул кончился — отдаём последний вариант."""
    builders = TEMPLATES[title]
    for _ in range(FRESH_TRIES):
        chosen = builders[rng.randrange(len(builders))]
        task = chosen(rng, "hard" if level == "hard" else "easy")
        if not exclude or task.prompt not in exclude:
            break
    return GeneratedTask(
        task.prompt,
        task.answer,
        task.hint,
        task.level,
        _STEPS[chosen],
    )
