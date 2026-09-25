"""The first answer is capped: a model that reasons inside its JSON answer (seen on v3 c02: 15,665
tokens, 227 s, then a 180 s client timeout) must end as a quick, explicit refusal, never as a
3-minute failure and never as half an answer."""

import pytest
from prometheus_client import REGISTRY

from app import providers
from app.api.ask import get_llm
from app.api.search import get_embedder, get_escalation_llm
from app.config import Settings, get_settings
from app.main import app
from tests.fakes import FakeEmbedder, ScriptedLLM

MD = b"# Towers\nOverview.\n\n## Cannon\nThe Cannon costs 120 gold.\n"
QUESTION = "how much does the cannon cost"
COMPLETE_LOOKING = {
    "answerable": True,
    "answer": "The Cannon costs 120 gold [1].",
    "citations": [1],
}


def refusals(reason: str) -> float:
    labels = {"outcome": "refused", "reason": reason}
    return REGISTRY.get_sample_value("ask_outcomes_total", labels) or 0.0


class Never:
    """An escalation model that must not be consulted."""

    calls = 0

    def generate(self, system: str, user: str):
        Never.calls += 1
        raise AssertionError("a truncated first answer must not be re-checked")


@pytest.fixture
def ask_with(client):
    def start(llm: ScriptedLLM, *, calculator: bool = False, escalation: str = "always") -> dict:
        app.dependency_overrides[get_llm] = lambda: llm
        app.dependency_overrides[get_escalation_llm] = lambda: Never()
        app.dependency_overrides[get_settings] = lambda: Settings(
            chunk_max_chars=300,
            min_evidence_score=0.2,
            llm_escalation=escalation,
            ask_calculator=calculator,
        )
        return client.post("/ask", json={"question": QUESTION}).json()

    app.dependency_overrides[get_embedder] = FakeEmbedder
    app.dependency_overrides[get_settings] = lambda: Settings(chunk_max_chars=300)
    client.post("/documents", files={"file": ("towers.md", MD)}, data={"source_path": "d/t.md"})
    client.post("/embeddings")
    yield start
    for dep in (get_embedder, get_llm, get_escalation_llm):
        app.dependency_overrides.pop(dep, None)


@pytest.mark.integration
@pytest.mark.parametrize(
    "reply",
    [
        COMPLETE_LOOKING,  # parses and cites a real source: the dangerous case
        '{"answerable": true, "answer": "You get 180 gold. Wait, let\'s re-calc',  # a fragment
    ],
    ids=["complete-looking", "fragment"],
)
def test_a_cut_off_first_answer_is_refused_as_answer_truncated(ask_with, reply):
    before, Never.calls = refusals("answer_truncated"), 0
    body = ask_with(ScriptedLLM(reply, truncated=True))
    assert body["refused"] is True and body["reason"] == "answer_truncated"
    assert body["answer"] is None and body["sources"] == []
    assert body["usage"] == {"prompt_tokens": 120, "completion_tokens": 15}  # still accounted
    assert Never.calls == 0  # no thinking re-check of a fragment
    assert refusals("answer_truncated") == before + 1


@pytest.mark.integration
def test_the_calculator_path_refuses_a_cut_off_answer_too(ask_with):
    body = ask_with(ScriptedLLM(COMPLETE_LOOKING, truncated=True), calculator=True)
    assert body["reason"] == "answer_truncated"


@pytest.mark.integration
def test_a_complete_answer_is_unaffected(ask_with):
    body = ask_with(ScriptedLLM(COMPLETE_LOOKING), escalation="off")
    assert body["refused"] is False and body["answer"] == "The Cannon costs 120 gold [1]."


def test_the_shipped_cap_is_1024_tokens() -> None:
    assert Settings.model_fields["llm_max_tokens"].default == 1024


def test_the_cap_applies_to_the_non_thinking_model_only() -> None:
    # Ollama counts thinking tokens toward num_predict, so 1024 would cut the reasoning itself.
    assert providers.answer_token_cap(Settings(llm_think=False)) == 1024
    assert providers.answer_token_cap(Settings(llm_think=True)) is None
    assert providers.answer_token_cap(Settings(llm_max_tokens=0)) is None  # 0 = no cap
