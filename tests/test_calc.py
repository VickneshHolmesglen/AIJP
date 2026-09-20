"""The calculator: correctness on the arithmetic the corpus needs, and a hostile-input suite."""

from decimal import Decimal

import pytest

from app.calc import CalcError, evaluate, format_number


def calc(expression: str, **variables: str) -> str:
    return format_number(evaluate(expression, {k: Decimal(v) for k, v in variables.items()}))


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2", "3"),
        ("0.75 * 120 * 2", "180"),
        ("120 + 0.75*120*2 + 0.75*120*3", "570"),
        ("12 * 1.2", "14.4"),  # exact decimal: a float would give 14.399999999999999
        ("(120 + 0.75*120*2 + 0.75*120*3) * 0.6", "342"),
        ("10 * 0.8", "8"),
        ("7 / 2", "3.5"),
        ("1 / 3", "0.333333"),
        ("-5 + 2", "-3"),
        ("--5", "5"),
        ("2 * (3 + 4) - 1", "13"),
        ("min(600 * 0.05, 50)", "30"),
        ("min(2000 * 0.05, 50)", "50"),
        ("max(1, 12 - 8)", "4"),
        ("max(1, 1 - 8)", "1"),
        ("int(112.5)", "112"),
        ("int(-2.9)", "-2"),
        ("round(2.5)", "3"),
        ("round(112.5)", "113"),
        ("abs(3 - 10)", "7"),
        ("60 / 12", "5"),
        ("4 * 3 * 5", "60"),
        ("3 × 4", "12"),  # the multiplication and minus signs a model tends to write
        ("10 ÷ 4", "2.5"),
        ("5 − 2", "3"),
    ],
)
def test_arithmetic_is_exact(expression: str, expected: str) -> None:
    assert calc(expression) == expected


def test_earlier_results_can_be_referenced() -> None:
    assert calc("c1 * 2 + c2", c1="90", c2="0.5") == "180.5"


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "   ",
        "1 +",
        "* 2",
        "(1 + 2",
        "1 + 2)",
        "1 2",
        "1 / 0",
        "1 / (2 - 2)",
        "2 ** 8",  # no exponent operator: it could be abused for huge numbers
        "10 % 3",
        "1e5",
        "0x10",
        "1_000",
        "$5",
        "min()",
        "round(1, 2)",
        "int(1, 2)",
        "unknown + 1",
        "c9 + 1",  # a result that does not exist
        "__import__('os').system('echo hi')",
        "open('/etc/passwd')",
        "().__class__",
        "print(1)",
        "lambda: 1",
        "[1, 2][0]",
        "1; 2",
        "1\n+ 2 + os",
        "9" * 40,  # literal too long
        "999999999999999 * 999999999999999",  # result too large
        "(" * 50 + "1" + ")" * 50,  # nesting bomb
        "1 + " * 200 + "1",  # too long
    ],
)
def test_anything_outside_the_tiny_language_is_rejected(expression: str) -> None:
    with pytest.raises(CalcError):
        evaluate(expression)


def test_non_string_input_is_rejected() -> None:
    with pytest.raises(CalcError):
        evaluate(5)  # type: ignore[arg-type]


def test_number_formatting() -> None:
    assert format_number(Decimal("14.4000")) == "14.4"
    assert format_number(Decimal("100")) == "100"
    assert format_number(Decimal("1E+2")) == "100"
    assert format_number(Decimal("0.0000001")) == "0"
    assert format_number(Decimal("-0.0000001")) == "0"
    assert format_number(Decimal("2.5000005")) == "2.500001"
