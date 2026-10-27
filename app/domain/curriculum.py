from dataclasses import dataclass


@dataclass(frozen=True)
class WorkedExample:
    text: str


@dataclass(frozen=True)
class PracticeTask:
    prompt: str
    answer: str
    hint: str


@dataclass(frozen=True)
class TopicMaterial:
    title: str
    explanation: str
    examples: tuple[WorkedExample, ...]
    tasks: tuple[PracticeTask, ...]


TOPICS: tuple[TopicMaterial, ...] = (
    TopicMaterial(
        title="Дроби",
        explanation=(
            "Дробь показывает часть целого: числитель — сколько частей взяли, "
            "знаменатель — на сколько частей разделили. "
            "Складывай и вычитай дроби только с общим знаменателем."
        ),
        examples=(
            WorkedExample("1/2 + 1/4. Общий знаменатель 4, 1/2 = 2/4. 2/4 + 1/4 = 3/4."),
            WorkedExample("2/3 − 1/3. Знаменатель уже общий. 2/3 − 1/3 = 1/3."),
        ),
        tasks=(
            PracticeTask(
                "Сложи 1/3 и 1/6. Напиши результат дробью.",
                "1/2",
                "Приведи к общему знаменателю и сложи числители.",
            ),
            PracticeTask(
                "Вычти 1/4 из 3/4. Напиши результат дробью.",
                "1/2",
                "Знаменатель уже общий, вычитай числители.",
            ),
        ),
    ),
    TopicMaterial(
        title="Линейные уравнения",
        explanation=(
            "В линейном уравнении неизвестное в первой степени. "
            "Перенеси числа в одну сторону, неизвестное в другую, затем раздели."
        ),
        examples=(
            WorkedExample("3x = 12. Раздели обе части на 3. x = 4."),
            WorkedExample("x − 2 = 6. Прибавь 2 к обеим частям. x = 8."),
        ),
        tasks=(
            PracticeTask(
                "Реши 2x = 10. Напиши число x.",
                "5",
                "Раздели обе части на число перед x.",
            ),
            PracticeTask(
                "Реши x + 6 = 10. Напиши число x.",
                "4",
                "Перенеси число в другую часть и поменяй знак.",
            ),
        ),
    ),
    TopicMaterial(
        title="Квадратные уравнения и дискриминант",
        explanation=(
            "Для ax² + bx + c = 0 дискриминант D = b² − 4ac. "
            "D > 0 — два корня, D = 0 — один, D < 0 — действительных корней нет."
        ),
        examples=(
            WorkedExample("x² − 5x + 6 = 0. D = 25 − 24 = 1. Корни (5 ± 1) / 2, то есть 3 и 2."),
            WorkedExample("x² + 1 = 0. D = −4. Действительных корней нет."),
        ),
        tasks=(
            PracticeTask(
                "Найди D для x² − x − 1 = 0. Напиши число.",
                "5",
                "Подставь коэффициенты в формулу дискриминанта.",
            ),
            PracticeTask(
                "Найди D для x² + 2x + 1 = 0. Напиши число.",
                "0",
                "Посмотри, сходится ли подстановка коэффициентов в ноль.",
            ),
        ),
    ),
    TopicMaterial(
        title="Геометрия",
        explanation=(
            "В прямоугольном треугольнике квадрат гипотенузы равен сумме квадратов катетов: "
            "c² = a² + b²."
        ),
        examples=(
            WorkedExample("Катеты 3 и 4. 9 + 16 = 25, гипотенуза 5."),
            WorkedExample("Катеты 8 и 15. 64 + 225 = 289, гипотенуза 17."),
        ),
        tasks=(
            PracticeTask(
                "Катеты 6 и 8. Чему равна гипотенуза?",
                "10",
                "Сложи квадраты катетов и извлеки корень.",
            ),
            PracticeTask(
                "Катеты 5 и 12. Чему равна гипотенуза?",
                "13",
                "Сложи квадраты катетов и извлеки корень.",
            ),
        ),
    ),
)

DEMO_CLASS_TITLE = "8Б"
DEMO_SUBJECT_TITLE = "Математика"


def topic_by_title(title: str) -> TopicMaterial | None:
    for material in TOPICS:
        if material.title == title:
            return material
    return None


def detect_topic(text: str) -> str | None:
    folded = text.casefold()
    if "дроб" in folded or "числител" in folded or "знаменател" in folded:
        return TOPICS[0].title
    if "дискриминант" in folded or "квадрат" in folded:
        return TOPICS[2].title
    if any(word in folded for word in ("геометр", "треуголь", "пифагор", "катет", "гипотенуз")):
        return TOPICS[3].title
    if "линейн" in folded or "уравнен" in folded:
        return TOPICS[1].title
    return None
