"""Escalation: answer normally, re-ask with (capped) thinking only when the answer holds a number
the sources do not, and fall back to the first answer whenever the second one fails."""

import json

import httpx
import pytest
from prometheus_client import REGISTRY

from app.api.ask import get_llm
from app.api.search import get_embedder, get_escalation_llm
from app.config import Settings, get_settings
from app.llm import Completion, LLMError, OllamaLLM
from app.main import app
from tests.fakes import FakeEmbedder, ScriptedLLM

MD = (
    b"# Towers\nOverview of towers.\n\n## Cannon\nThe Cannon costs 120 gold. Upgrading to level N "
    b"costs 0.75 times the base cost times N.\n\n## Fire\nFire burns for 5 seconds.\n"
)
QUESTION = "how much does upgrading the cannon to level 2 cost"


def answer(text: str, citations=(1,)) -> dict:
    return {"answerable": True, "answer": text, "citations": list(citations)}


class Second:
    """The escalation model: scripted, and records whether it was consulted."""

    def __init__(self, reply=None, *, truncated: bool = False, error: Exception | None = None):
        self.reply, self.truncated, self.error = reply, truncated, error
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> Completion:
        self.calls.append((system, user))
        if self.error:
            raise self.error
        return Completion(
            json.dumps(self.reply),
            prompt_tokens=200,
            completion_tokens=900,
            truncated=self.truncated,
        )


def count(outcome: str) -> float:
    return REGISTRY.get_sample_value("escalation_total", {"outcome": outcome}) or 0.0


@pytest.fixture
def stack(client):
    def start(first: dict, second: Second | None, mode: str = "derived") -> ScriptedLLM:
        llm = ScriptedLLM(first)
        app.dependency_overrides[get_llm] = lambda: llm
        app.dependency_overrides[get_escalation_llm] = lambda: second
        app.dependency_overrides[get_settings] = lambda: Settings(
            chunk_max_chars=300,
            chunk_overlap_chars=60,
            min_evidence_score=0.2,
            llm_escalation=mode,
        )
        return llm

    app.dependency_overrides[get_embedder] = FakeEmbedder
    app.dependency_overrides[get_settings] = lambda: Settings(
        chunk_max_chars=300, chunk_overlap_chars=60
    )
    client.post("/documents", files={"file": ("towers.md", MD)}, data={"source_path": "d/t.md"})
    client.post("/embeddings")
    yield start
    for dep in (get_embedder, get_llm, get_escalation_llm):
        app.dependency_overrides.pop(dep, None)


def ask(client) -> dict:
    return client.post("/ask", json={"question": QUESTION}).json()


# ------------------------------------------------------------------ the trigger


@pytest.mark.integration
def test_a_derived_number_triggers_a_second_thinking_answer_that_replaces_the_first(client, stack):
    second = Second(answer("Upgrading to level 2 costs 180 gold [1]."))
    stack(answer("Upgrading to level 2 costs 160 gold [1]."), second)  # the first is wrong
    before = count("used")
    body = ask(client)
    assert (
        body["answer"] == "Upgrading to level 2 costs 180 gold [1]." and body["escalated"] == "used"
    )
    assert len(second.calls) == 1
    assert body["usage"] == {
        "prompt_tokens": 120 + 200,
        "completion_tokens": 15 + 900,
    }  # both calls
    assert count("used") == before + 1


@pytest.mark.integration
def test_a_number_quoted_from_the_sources_does_not_escalate(client, stack):
    second = Second(answer("unused"))
    stack(answer("The Cannon costs 120 gold [1]."), second)  # 120 is in the passage
    body = ask(client)
    assert body["escalated"] is None and second.calls == []
    assert body["answer"] == "The Cannon costs 120 gold [1]."


@pytest.mark.integration
def test_a_number_from_the_question_is_not_derived(client, stack):
    second = Second(answer("unused"))
    stack(answer("Upgrading to level 2 uses the formula [1]."), second)  # 2 is in the question
    assert ask(client)["escalated"] is None and second.calls == []


@pytest.mark.integration
def test_always_mode_escalates_every_answer(client, stack):
    second = Second(answer("The Cannon costs 120 gold [1]."))
    stack(answer("The Cannon costs 120 gold [1]."), second, mode="always")
    assert ask(client)["escalated"] == "used" and len(second.calls) == 1


@pytest.mark.integration
def test_off_really_turns_it_off_and_derived_is_the_shipped_default(client, stack):
    second = Second(answer("unused"))
    stack(answer("Upgrading to level 2 costs 160 gold [1]."), second, mode="off")
    body = ask(client)
    assert body["escalated"] is None and second.calls == []
    # The shipped default (the test suite overrides it through the environment, see conftest.py).
    assert Settings.model_fields["llm_escalation"].default == "derived"
    assert Settings.model_fields["llm_escalation_tokens"].default == 1500


@pytest.mark.integration
def test_no_second_model_configured_means_no_escalation(client, stack):
    stack(answer("Upgrading to level 2 costs 160 gold [1]."), None)
    assert ask(client)["escalated"] is None


@pytest.mark.integration
def test_an_evidence_gate_refusal_never_reaches_either_model(client, stack):
    second = Second(answer("unused"))
    first = stack(answer("x [1]"), second)
    app.dependency_overrides[get_settings] = lambda: Settings(
        chunk_max_chars=300, min_evidence_score=0.99, llm_escalation="derived"
    )
    body = ask(client)
    assert body["reason"] == "insufficient_evidence" and first.calls == [] and second.calls == []


# ------------------------------------------------------------------ fallbacks and checks


@pytest.mark.integration
@pytest.mark.parametrize(
    "second",
    [
        Second(answer("Costs 180 gold [1]."), truncated=True),  # cut off at the token cap
        Second(error=LLMError("timed out")),
    ],
    ids=["truncated", "error"],
)
def test_a_failed_or_cut_off_second_pass_keeps_the_first_answer(client, stack, second):
    stack(answer("Upgrading to level 2 costs 160 gold [1]."), second)
    before = count("fallback")
    body = ask(client)
    assert body["answer"] == "Upgrading to level 2 costs 160 gold [1]."
    assert body["escalated"] == "fallback" and body["refused"] is False
    assert count("fallback") == before + 1


@pytest.mark.integration
def test_the_second_answer_faces_the_same_citation_check(client, stack):
    second = Second(answer("Costs 180 gold [99].", citations=(99,)))  # cites nothing real
    stack(answer("Upgrading to level 2 costs 160 gold [1]."), second)
    body = ask(client)
    assert body["refused"] is True and body["reason"] == "uncited_answer"
    assert body["escalated"] == "used" and body["answer"] is None


@pytest.mark.integration
def test_a_second_pass_that_declines_is_respected(client, stack):
    second = Second({"answerable": False})
    stack(answer("Upgrading to level 2 costs 160 gold [1]."), second)
    body = ask(client)
    assert body["refused"] is True and body["reason"] == "model_declined"


# ------------------------------------------------------------------ the token cap itself


def ollama(handler, **kwargs) -> OllamaLLM:
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://ollama")
    return OllamaLLM("http://ollama", "m", client=client, **kwargs)


def test_the_cap_is_sent_to_ollama_and_a_length_stop_is_reported_as_truncated() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200, json={"message": {"content": "partial"}, "done_reason": "length", "eval_count": 5}
        )

    completion = ollama(handler, think=True, max_tokens=1500).generate("s", "u")
    assert seen["options"]["num_predict"] == 1500 and seen["think"] is True
    assert completion.truncated is True


def test_no_cap_means_no_num_predict_and_a_normal_stop_is_not_truncated() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "ok"}, "done_reason": "stop"})

    completion = ollama(handler).generate("s", "u")
    assert "num_predict" not in seen["options"] and completion.truncated is False


def test_a_slow_thinking_call_times_out_into_a_llm_error_so_the_first_answer_can_stand() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("model too slow", request=request)

    with pytest.raises(LLMError):
        ollama(handler, think=True, max_tokens=1500).generate("s", "u")
    assert Settings.model_fields["llm_escalation_timeout_seconds"].default == 45.0
