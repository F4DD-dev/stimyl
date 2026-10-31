import pytest

from app.domain.answers import answers_match, is_attempt


@pytest.mark.parametrize(
    ("expected", "given"),
    [
        ("1/2", "1/2"),
        ("1/2", "0,5"),
        ("1/2", "0.5"),
        ("5", "x = 5"),
        ("5", "ответ: 5"),
        ("5", "5.0"),
        ("5", "5."),
        ("-3", "−3"),
        ("1/2", "½"),
        ("2 и 3", "3 и 2"),
        ("2 и 3", "x1=2; x2=3"),
        ("5", "D=5"),
        ("10", "10 см"),
        ("1000", "1 000"),
        ("5", "5.001"),
    ],
)
def test_answer_table(expected, given):
    assert answers_match(expected, given)


@pytest.mark.parametrize(
    ("expected", "given"),
    [
        ("5", "4"),
        ("5", "5.01"),
        ("5", ""),
        ("2 и 3", "2 и 4"),
        ("5", "не знаю"),
        ("5", "?"),
        ("5", "подскажи"),
    ],
)
def test_answer_table_rejects(expected, given):
    assert not answers_match(expected, given)


def test_uncertainty_is_not_an_attempt():
    assert not is_attempt("не знаю")
    assert not is_attempt("?")
    assert not is_attempt("Подскажи")
    assert is_attempt("5")
    assert is_attempt("нет")


def test_parser_does_not_call_eval():
    source = open("app/domain/answers.py", encoding="utf-8").read()
    assert "eval(" not in source
    assert "exec(" not in source
