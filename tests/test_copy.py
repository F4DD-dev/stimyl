from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = ("app", "alembic")
SUFFIXES = {".py", ".js", ".html", ".css", ".sql"}
BANNED = (
    "я стимул",
    "готовый ответ к твоей задаче не пишу",
    "пришли вопрос",
    "страницу за ученика не решаю",
)


def test_old_greeting_does_not_return():
    """Старое представление бота не должно вернуться в код, сиды, миграции и описание."""
    hits: list[str] = []
    for folder in SCAN:
        base = ROOT / folder
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUFFIXES:
                continue
            text = path.read_text(encoding="utf-8").casefold()
            for phrase in BANNED:
                if phrase in text:
                    hits.append(f"{path.relative_to(ROOT)}: {phrase}")
    assert hits == []
