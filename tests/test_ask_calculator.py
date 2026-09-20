"""Calculator mode in grounded Q&A: the model writes arithmetic, the server computes it."""

import json

import pytest

from app.api.ask import get_llm
from app.api.search import get_embedder
from app.config import Settings, get_settings
from app.main import app
from app.qa import Calculation, run_calculations, ungrounded_numbers
from tests.fakes import FakeEmbedder, ScriptedLLM

MD = (
    b"# Towers\nOverview of towers.\n\n## Cannon\nThe Cannon costs 120 gold. Upgrading to level N "
    b"costs 0.75 times the base cost times N.\n\n## Fire\nFire burns for 5 seconds.\n"
)
QUESTION = "how much does upgrading the cannon to level 2 cost"


def reply(answer: str, calculations, citations=(1,)) -> dict:
    return {
        "answerable": True,
        "answer": answer,
        "citations": list(citations),
        "calculations": calculations,
    }


# ------------------------------------------------------------------ pure logic (no database)


def test_placeholders_are_filled_with_exact_results() -> None:
    raw = json.dumps(
        reply(
            "It costs {c1} gold, {c2} in total [1].",
            [
                {"id": "c1", "expression": "0.75 * 120 * 2"},
                {"id": "c2", "expression": "120 + c1"},
            ],
        )
    )
    text, calcs = run_calculations(raw, "It costs {c1} gold, {c2} in total [1].") or ("", ())
    assert text == "It costs 180 gold, 300 in total [1]."
    assert [(c.id, c.expression, c.result) for c in calcs] == [
        ("c1", "0.75 * 120 * 2", "180"),
        ("c2", "120 + c1", "300"),
    ]


def test_no_calculations_and_no_placeholders_passes_through() -> None:
    raw = json.dumps({"answerable": True, "answer": "It is 5.", "citations": [1]})
    assert run_calculations(raw, "It is 5.") == ("It is 5.", ())
    assert run_calculations(json.dumps(reply("Five.", [])), "Five.") == ("Five.", ())


@pytest.mark.parametrize(
    "calculations",
    [
        [{"id": "c1", "expression": "__import__('os').system('id')"}],
        [{"id": "c1", "expression": "1 / 0"}],
        [{"id": "c1", "expression": "2 ** 999"}],
        [{"id": "c1", "expression": 5}],
        [{"id": "x1", "expression": "1"}],  # ids must look like c1, c2, ...
        [{"id": "c1", "expression": "1"}, {"id": "c1", "expression": "2"}],  # duplicate id
        [{"expression": "1"}],
        ["1 + 1"],
        "1 + 1",
        [{"id": f"c{i}", "expression": "1"} for i in range(1, 10)],  # more than the maximum
    ],
)
def test_bad_calculations_fail_closed(calculations) -> None:
    raw = json.dumps(reply("It is {c1}.", calculations))
    assert run_calculations(raw, "It is {c1}.") is None


def test_a_placeholder_without_a_calculation_fails_closed() -> None:
    raw = json.dumps(reply("It is {c2}.", [{"id": "c1", "expression": "1"}]))
    assert run_calculations(raw, "It is {c2}.") is None
    assert run_calculations("not json", "It is {c1}.") is None


# ------------------------------------------------------------------ grounded numbers

SOURCE = "The Cannon costs 120 gold. Upgrading to level N costs 0.75 times the base cost times N."
CALC = (Calculation("c1", "0.75*120*2", "180"),)


def test_numbers_from_calculations_sources_and_the_question_are_grounded() -> None:
    q = "How much to upgrade to level 2?"
    assert ungrounded_numbers("It costs 180 gold [1].", q, SOURCE, CALC) == []
    assert ungrounded_numbers("The Cannon costs 120 gold [1, 2].", q, SOURCE, CALC) == []
    assert ungrounded_numbers("Level 2 costs 180.", q, SOURCE, CALC) == []  # 2 is in the question
    assert ungrounded_numbers("It is 0.750 times.", q, SOURCE, CALC) == []  # same number as 0.75
    assert ungrounded_numbers("It is 1,800 gold.", q, "Costs 1800 gold.", ()) == []  # separators


def test_a_number_the_model_made_up_or_computed_itself_is_caught() -> None:
    q = "How much to upgrade to level 2?"
    assert ungrounded_numbers("It costs 185 gold [1].", q, SOURCE, CALC) == ["185"]
    assert ungrounded_numbers("It costs 180 or 185 gold.", q, SOURCE, CALC) == ["185"]
    assert ungrounded_numbers("It costs 185 gold.", q, SOURCE, ()) == ["185"]  # no calculation
    assert ungrounded_numbers("No numbers here [3].", q, SOURCE, ()) == []
    assert ungrounded_numbers("Costs 1250 gold.", q, "It is 1,250 gold.", ()) == []


# ------------------------------------------------------------------ through the API


@pytest.fixture
def stack(client):
    def start(llm_reply, calculator: bool = True) -> ScriptedLLM:
        llm = ScriptedLLM(llm_reply)
        app.dependency_overrides[get_llm] = lambda: llm
        app.dependency_overrides[get_settings] = lambda: Settings(
            chunk_max_chars=300,
            chunk_overlap_chars=60,
            min_evidence_score=0.2,
            ask_calculator=calculator,
        )
        return llm

    app.dependency_overrides[get_embedder] = FakeEmbedder
    app.dependency_overrides[get_settings] = lambda: Settings(
        chunk_max_chars=300, chunk_overlap_chars=60
    )
    client.post("/documents", files={"file": ("towers.md", MD)}, data={"source_path": "d/t.md"})
    client.post("/embeddings")
    yield start
    app.dependency_overrides.pop(get_embedder, None)
    app.dependency_overrides.pop(get_llm, None)


@pytest.mark.integration
def test_the_server_computes_the_number_and_shows_its_working(client, stack) -> None:
    llm = stack(reply("Upgrading costs {c1} gold [1].", [{"id": "c1", "expression": "0.75*120*2"}]))
    body = client.post("/ask", json={"question": QUESTION}).json()
    assert body["refused"] is False
    assert body["answer"] == "Upgrading costs 180 gold [1]."
    assert body["calculations"] == [{"id": "c1", "expression": "0.75*120*2", "result": "180"}]
    assert "NEVER compute a number yourself" in llm.calls[0][0]  # the calculator prompt was used


@pytest.mark.integration
def test_a_hostile_expression_withholds_the_answer(client, stack) -> None:
    stack(reply("It is {c1}.", [{"id": "c1", "expression": "__import__('os').getcwd()"}]))
    body = client.post("/ask", json={"question": QUESTION}).json()
    assert body["refused"] is True and body["reason"] == "calculation_failed"
    assert body["answer"] is None and body["calculations"] == []


@pytest.mark.integration
def test_an_answer_with_no_arithmetic_is_unchanged(client, stack) -> None:
    stack(reply("Fire burns for 5 seconds [1].", []))
    body = client.post("/ask", json={"question": "how long does fire burn"}).json()
    assert body["refused"] is False and body["answer"] == "Fire burns for 5 seconds [1]."
    assert body["calculations"] == []


@pytest.mark.integration
def test_calculator_mode_is_off_by_default_and_uses_the_standard_prompt(client, stack) -> None:
    llm = stack(reply("Upgrading costs {c1} gold [1].", [{"id": "c1", "expression": "1+1"}]), False)
    body = client.post("/ask", json={"question": QUESTION}).json()
    assert body["calculations"] == []
    assert body["answer"] == "Upgrading costs {c1} gold [1]."  # nothing is substituted when off
    assert "calculations" not in llm.calls[0][0]
    assert Settings().ask_calculator is False


@pytest.mark.integration
def test_citations_are_still_required_in_calculator_mode(client, stack) -> None:
    stack(reply("It costs {c1}.", [{"id": "c1", "expression": "1"}], citations=(99,)))
    body = client.post("/ask", json={"question": QUESTION}).json()
    assert body["refused"] is True and body["reason"] == "uncited_answer"


@pytest.mark.integration
def test_a_literal_number_the_model_computed_itself_is_withheld(client, stack) -> None:
    # It wrote a calculation (result 180) but ignored the placeholder and typed its own number.
    stack(reply("Upgrading costs 185 gold [1].", [{"id": "c1", "expression": "0.75*120*2"}]))
    body = client.post("/ask", json={"question": QUESTION}).json()
    assert body["refused"] is True and body["reason"] == "ungrounded_number"
    assert body["answer"] is None


@pytest.mark.integration
def test_numbers_quoted_from_the_sources_are_allowed_beside_a_calculation(client, stack) -> None:
    stack(
        reply(
            "The Cannon costs 120 gold, so level 2 costs {c1} gold [1].",
            [{"id": "c1", "expression": "0.75 * 120 * 2"}],
        )
    )
    body = client.post("/ask", json={"question": QUESTION}).json()
    assert body["refused"] is False
    assert body["answer"] == "The Cannon costs 120 gold, so level 2 costs 180 gold [1]."
