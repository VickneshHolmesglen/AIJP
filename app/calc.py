"""A small, safe arithmetic evaluator for the "calculator" step of grounded Q&A.

Why this exists: on questions that need a derived number ("what does it cost to upgrade a Cannon
Tower to level 2?") the local model finds the right facts and then gets the arithmetic wrong
(eval/results/qa-v2-*: multi-hop 4/11 correct, with the right chunks retrieved). Language models
are unreliable calculators, but they are good at writing an expression. So the model writes the
expression and this module computes it exactly.

It is a hand-written recursive-descent parser, not Python's `eval`/`ast`: the model's output is
untrusted input steered by untrusted document text, so the accepted language is deliberately tiny
and there is no way to reach names, attributes, calls or imports, whatever the text says.

Accepted: decimal numbers, + - * / (unary minus too), parentheses, the functions min, max, round,
int (truncate, like GDScript's int()) and abs, and references to earlier results (c1, c2, ...).
Everything is exact decimal arithmetic, so 12 * 1.2 is 14.4, not 14.399999999999999.
"""

import re
from decimal import ROUND_HALF_UP, Decimal, DivisionByZero, InvalidOperation, localcontext

MAX_EXPRESSION_CHARS = 200
MAX_DEPTH = 20
MAX_ABS_VALUE = Decimal("1e15")
_MAX_LITERAL_DIGITS = 15
_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?)|([A-Za-z_]\w*)|(.))")
_FUNCTIONS = {"min", "max", "round", "int", "abs"}
_NORMALISE = str.maketrans({"×": "*", "÷": "/", "−": "-", "–": "-"})


class CalcError(ValueError):
    """The expression is not valid arithmetic (or is too big). The message is safe to log."""


class _Parser:
    def __init__(self, text: str, variables: dict[str, Decimal]) -> None:
        self.tokens = self._tokenise(text)
        self.pos = 0
        self.variables = variables
        self.depth = 0

    @staticmethod
    def _tokenise(text: str) -> list[tuple[str, str]]:
        tokens: list[tuple[str, str]] = []
        pos = 0
        while pos < len(text):
            match = _TOKEN.match(text, pos)
            if match is None or match.end() == pos:
                break
            number, name, symbol = match.groups()
            pos = match.end()
            if number is not None:
                if len(number.replace(".", "")) > _MAX_LITERAL_DIGITS:
                    raise CalcError("number too long")
                tokens.append(("num", number))
            elif name is not None:
                tokens.append(("name", name))
            elif symbol is not None:
                if symbol not in "+-*/(),":
                    raise CalcError(f"unexpected character {symbol!r}")
                tokens.append(("sym", symbol))
        if text[pos:].strip():
            raise CalcError("could not read the whole expression")
        return tokens

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, symbol: str | None = None) -> tuple[str, str]:
        token = self.peek()
        if token is None or (symbol is not None and token != ("sym", symbol)):
            raise CalcError(f"expected {symbol!r}" if symbol else "unexpected end")
        self.pos += 1
        return token

    def parse(self) -> Decimal:
        value = self.expression()
        if self.peek() is not None:
            raise CalcError("unexpected trailing input")
        return value

    def expression(self) -> Decimal:
        value = self.term()
        while (tok := self.peek()) in (("sym", "+"), ("sym", "-")):
            self.take()
            rhs = self.term()
            value = value + rhs if tok == ("sym", "+") else value - rhs
            _check(value)
        return value

    def term(self) -> Decimal:
        value = self.unary()
        while (tok := self.peek()) in (("sym", "*"), ("sym", "/")):
            self.take()
            rhs = self.unary()
            if tok == ("sym", "*"):
                value = value * rhs
            else:
                if rhs == 0:
                    raise CalcError("division by zero")
                value = value / rhs
            _check(value)
        return value

    def unary(self) -> Decimal:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise CalcError("expression nested too deeply")
        try:
            if (tok := self.peek()) in (("sym", "-"), ("sym", "+")):
                self.take()
                inner = self.unary()
                return -inner if tok == ("sym", "-") else inner
            return self.atom()
        finally:
            self.depth -= 1

    def atom(self) -> Decimal:
        kind, text = self.take()
        if kind == "num":
            return Decimal(text)
        if kind == "sym" and text == "(":
            value = self.expression()
            self.take(")")
            return value
        if kind == "name":
            if text in _FUNCTIONS:
                return self.call(text)
            if text in self.variables:
                return self.variables[text]
            raise CalcError(f"unknown name {text!r}")
        raise CalcError(f"unexpected {text!r}")

    def call(self, name: str) -> Decimal:
        self.take("(")
        args = [self.expression()]
        while self.peek() == ("sym", ","):
            self.take(",")
            args.append(self.expression())
        self.take(")")
        if name in ("min", "max"):
            return min(args) if name == "min" else max(args)
        if len(args) != 1:
            raise CalcError(f"{name}() takes one argument")
        (x,) = args
        if name == "abs":
            return abs(x)
        if name == "int":
            return x.to_integral_value(rounding="ROUND_DOWN")  # truncate toward zero
        return x.quantize(Decimal(1), rounding=ROUND_HALF_UP)  # round


def _check(value: Decimal) -> None:
    if abs(value) > MAX_ABS_VALUE:
        raise CalcError("number too large")


def evaluate(expression: str, variables: dict[str, Decimal] | None = None) -> Decimal:
    """Exact value of `expression`. Raises CalcError for anything outside the tiny language."""
    if not isinstance(expression, str) or not expression.strip():
        raise CalcError("empty expression")
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise CalcError("expression too long")
    try:
        with localcontext() as ctx:
            ctx.prec = 40
            return _Parser(expression.translate(_NORMALISE), variables or {}).parse()
    except (InvalidOperation, DivisionByZero) as exc:
        raise CalcError("invalid arithmetic") from exc


def format_number(value: Decimal, places: int = 6) -> str:
    """Plain decimal text: no exponent, no trailing zeros, at most `places` decimals."""
    quantised = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    text = format(quantised, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text
