import pytest

from app.api.ask import get_llm
from app.api.search import get_embedder
from app.config import Settings, get_settings
from app.llm import LLMError
from app.main import app
from tests.fakes import FakeEmbedder, ScriptedLLM

pytestmark = pytest.mark.integration

MD = (
    b"# Towers\nOverview of towers.\n\n## Poison\nPoison stacks up to 3 times.\n\n"
    b"## Fire\nFire burns for 5 seconds.\n"
)


@pytest.fixture
def setup(client):
    """Ingest + embed the towers doc; returns a function that installs a scripted LLM."""
    app.dependency_overrides[get_embedder] = FakeEmbedder
    app.dependency_overrides[get_settings] = lambda: Settings(
        chunk_max_chars=300, chunk_overlap_chars=60, min_evidence_score=0.2
    )
    client.post("/documents", files={"file": ("towers.md", MD)}, data={"source_path": "d/t.md"})
    client.post("/embeddings")

    def install(reply):
        llm = ScriptedLLM(reply)
        app.dependency_overrides[get_llm] = lambda: llm
        return llm

    yield install
    app.dependency_overrides.pop(get_embedder, None)
    app.dependency_overrides.pop(get_llm, None)


def _poison_ref(client) -> int:
    """Ref number the retrieval assigns to the Poison chunk for our question."""
    hits = client.post("/search", json={"query": "poison stack limit"}).json()["hits"]
    return next(i for i, h in enumerate(hits, 1) if h["citation"]["section"] == "Towers > Poison")


def test_grounded_answer_with_verified_citation(client, setup):
    ref = _poison_ref(client)
    llm = setup({"answerable": True, "answer": f"Up to 3 [{ref}].", "citations": [ref]})

    body = client.post("/ask", json={"question": "poison stack limit"}).json()

    assert body["refused"] is False and body["reason"] is None
    assert body["usage"] == {"prompt_tokens": 120, "completion_tokens": 15}
    assert body["answer"] == f"Up to 3 [{ref}]."
    [source] = body["sources"]
    assert source["ref"] == ref
    assert source["chunk_id"]  # lets the UI highlight the exact cited passage
    assert source["citation"]["source_path"] == "d/t.md"
    assert source["citation"]["section"] == "Towers > Poison"
    assert (source["citation"]["start_line"], source["citation"]["end_line"]) == (4, 5)
    # The prompt really contained the numbered, provenance-tagged context.
    assert f"[{ref}] (path: d/t.md, section: Towers > Poison" in llm.calls[0][1]


def test_low_similarity_refuses_without_calling_llm(client, setup):
    llm = setup({"answerable": True, "answer": "x", "citations": [1]})
    body = client.post("/ask", json={"question": "zebra quantum spaghetti"}).json()
    assert body["refused"] is True and body["reason"] == "insufficient_evidence"
    assert body["answer"] is None and body["sources"] == []
    assert body["usage"] == {"prompt_tokens": 0, "completion_tokens": 0}
    assert llm.calls == []


def test_model_can_decline(client, setup):
    setup({"answerable": False, "answer": "", "citations": []})
    body = client.post("/ask", json={"question": "poison stack limit"}).json()
    assert body["refused"] is True and body["reason"] == "model_declined"


def test_hallucinated_citation_numbers_are_not_trusted(client, setup):
    setup({"answerable": True, "answer": "It is 3.", "citations": [99]})
    body = client.post("/ask", json={"question": "poison stack limit"}).json()
    assert body["refused"] is True and body["reason"] == "uncited_answer"
    assert body["sources"] == []


def test_only_valid_citations_are_returned(client, setup):
    ref = _poison_ref(client)
    setup({"answerable": True, "answer": "3", "citations": [ref, 99]})
    body = client.post("/ask", json={"question": "poison stack limit"}).json()
    assert [s["ref"] for s in body["sources"]] == [ref]


def test_unparseable_model_output_is_a_refusal_not_an_error(client, setup):
    setup("Sure! The answer is 3.")
    body = client.post("/ask", json={"question": "poison stack limit"}).json()
    assert body["refused"] is True and body["reason"] == "model_declined"


def test_llm_outage_returns_503(client, setup):
    setup(LLMError("Ollama request failed: refused"))
    assert client.post("/ask", json={"question": "poison stack limit"}).status_code == 503


def test_prompt_treats_sources_as_untrusted(client, setup):
    llm = setup({"answerable": False, "answer": "", "citations": []})
    client.post("/ask", json={"question": "poison stack limit"})
    assert "untrusted" in llm.calls[0][0]


def test_ask_validates_input(client, setup):
    assert client.post("/ask", json={"question": ""}).status_code == 422
