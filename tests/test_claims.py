import pytest

from app.agent.claims import extract_claims, locate_quote, parse_claims
from app.llm import LLMError
from tests.fakes import ScriptedLLM

PASSAGE = """### Arcane Lance
The **Arcane Lance** deals 30 damage per shot
and targets the enemy with the LOWEST_HP.

| `arcane_lance` | Arcane Lance | elemental | 3 | 24 |
Poison stacks up to 3 times."""


def test_quote_line_is_found_across_wrapping_and_markdown() -> None:
    assert locate_quote("The Arcane Lance deals 30 damage per shot and targets", PASSAGE, 10) == 11
    assert locate_quote("arcane_lance | Arcane Lance | elemental | 3 | 24", PASSAGE, 10) == 14
    assert locate_quote("Poison stacks up to 3 times.", PASSAGE, 10) == 15


def test_a_quote_not_in_the_passage_or_too_short_is_not_found() -> None:
    assert locate_quote("The Arcane Lance deals 40 damage per shot", PASSAGE, 1) is None
    assert locate_quote("30 damage", PASSAGE, 1) is None  # too short to identify a line


def reply(*pairs: tuple[str, str]) -> str:
    import json

    return json.dumps({"claims": [{"claim": c, "quote": q} for c, q in pairs]})


def test_only_claims_with_a_real_quote_are_kept_in_order() -> None:
    raw = reply(
        ("The Arcane Lance deals 30 damage per shot.", "deals 30 damage per shot"),
        ("The Arcane Lance deals 99 damage.", "deals 99 damage per shot"),  # invented
        ("Poison stacks up to 3 times.", "Poison stacks up to 3 times."),
    )
    claims = parse_claims(raw, PASSAGE, 1, max_claims=5)
    assert [(c.text, c.line) for c in claims] == [
        ("The Arcane Lance deals 30 damage per shot.", 2),
        ("Poison stacks up to 3 times.", 6),
    ]


def test_duplicates_are_dropped_and_the_cap_is_applied() -> None:
    raw = reply(
        ("Poison stacks up to 3 times.", "Poison stacks up to 3 times."),
        ("poison stacks up to 3 times.", "Poison stacks up to 3 times."),
        ("The Arcane Lance deals 30 damage per shot.", "deals 30 damage per shot"),
        ("It targets LOWEST_HP.", "targets the enemy with the LOWEST_HP"),
    )
    assert len(parse_claims(raw, PASSAGE, 1, max_claims=2)) == 2
    assert len(parse_claims(raw, PASSAGE, 1, max_claims=9)) == 3


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        '{"claims": "x"}',
        '{"claims": [1, null, {"claim": 5, "quote": "Poison stacks up to 3 times."}]}',
        '{"claims": [{"claim": "  ", "quote": "Poison stacks up to 3 times."}]}',
    ],
)
def test_malformed_replies_yield_no_claims(raw: str) -> None:
    assert parse_claims(raw, PASSAGE, 1, max_claims=5) == []


def test_extract_uses_the_model_and_ignores_a_truncated_reply() -> None:
    raw = reply(("Poison stacks up to 3 times.", "Poison stacks up to 3 times."))
    assert len(extract_claims(ScriptedLLM(raw), PASSAGE, "Combat", 1, 3)) == 1
    assert extract_claims(ScriptedLLM(raw, truncated=True), PASSAGE, None, 1, 3) == []


def test_an_unavailable_model_raises() -> None:
    with pytest.raises(LLMError):
        extract_claims(ScriptedLLM(LLMError("down")), PASSAGE, None, 1, 3)
