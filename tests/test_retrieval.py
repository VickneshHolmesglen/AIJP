import pytest

from app.api.search import get_embedder
from app.main import app
from app.retrieval import reciprocal_rank_fusion
from tests.fakes import FakeEmbedder

# ------------------------------------------------------------------ RRF (pure)


def test_rrf_scores_are_sum_of_reciprocal_ranks() -> None:
    scores = reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=60)
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["c"] == pytest.approx(1 / 62)


def test_rrf_rewards_agreement_between_rankers() -> None:
    # "b" is second in both lists; "a" and "c" are each first in only one.
    scores = reciprocal_rank_fusion([["a", "b"], ["c", "b"]])
    assert max(scores, key=scores.__getitem__) == "b"


def test_rrf_empty_and_single_list() -> None:
    assert reciprocal_rank_fusion([]) == {}
    assert list(reciprocal_rank_fusion([["x", "y"]])) == ["x", "y"]


# ------------------------------------------------------------------ integration

MD = (
    b"# Towers\nOverview of towers.\n\n## Poison\nPoison stacks up to 3 times.\n\n"
    b"## Fire\nFire burns for 5 seconds.\n"
)


@pytest.fixture
def embedder():
    app.dependency_overrides[get_embedder] = FakeEmbedder
    yield
    app.dependency_overrides.pop(get_embedder, None)


def upload(client, name="towers.md", content=MD, **data):
    return client.post("/documents", files={"file": (name, content)}, data=data)


def search(client, query, **body):
    response = client.post("/search", json={"query": query, **body})
    assert response.status_code == 200
    return response.json()["hits"]


@pytest.mark.integration
def test_lexical_finds_only_chunks_containing_query_terms(client, embedder):
    upload(client)
    client.post("/embeddings")
    hits = search(client, "poison", mode="lexical")
    assert [h["citation"]["section"] for h in hits] == ["Towers > Poison"]
    assert hits[0]["cosine"] is not None  # carried through for the evidence gate


@pytest.mark.integration
def test_lexical_uses_or_semantics_and_stemming(client, embedder):
    upload(client)
    # "burning" stems to "burn"; "zebra" matches nothing. AND semantics would return no hits.
    hits = search(client, "zebra burning", mode="lexical")
    assert [h["citation"]["section"] for h in hits] == ["Towers > Fire"]


@pytest.mark.integration
def test_lexical_works_before_embedding_with_null_cosine(client, embedder):
    upload(client)  # never embedded
    hits = search(client, "poison", mode="lexical")
    assert len(hits) == 1 and hits[0]["cosine"] is None
    assert search(client, "poison", mode="vector") == []


@pytest.mark.integration
def test_lexical_stopword_only_query_returns_nothing(client, embedder):
    upload(client)
    assert search(client, "the and of", mode="lexical") == []


@pytest.mark.integration
def test_lexical_matches_the_symbol_path_not_just_the_content(client, embedder):
    # Second chunk of a long function never mentions its name, but its section does.
    body = "\n".join(f"        total += compute_{i}(value) * 2  # filler line" for i in range(12))
    src = f"class Enemy:\n    def frobnicate(self, value):\n        total = 0\n{body}\n".encode()
    upload(client, "enemy.py", src)
    hits = search(client, "frobnicate", mode="lexical", top_k=10)
    assert len(hits) >= 2
    assert {h["citation"]["section"] for h in hits} == {"Enemy > frobnicate"}


@pytest.mark.integration
def test_hybrid_returns_union_of_both_retrievers(client, embedder):
    upload(client)
    other = upload(client, "notes.txt", b"unrelated words entirely").json()
    client.post("/embeddings")
    hybrid = search(client, "poison", mode="hybrid", top_k=10)
    ids = {h["chunk_id"] for h in hybrid}
    vector = {h["chunk_id"] for h in search(client, "poison", mode="vector", top_k=10)}
    lexical = {h["chunk_id"] for h in search(client, "poison", mode="lexical", top_k=10)}
    assert ids == vector | lexical
    assert hybrid[0]["citation"]["section"] == "Towers > Poison"  # both retrievers agree
    assert other["id"] in {h["citation"]["document_id"] for h in hybrid}  # vector-only candidate


@pytest.mark.integration
def test_hybrid_scores_are_descending_and_respect_top_k_and_document_filter(client, embedder):
    doc = upload(client).json()
    upload(client, "notes.txt", b"poison is also here")
    client.post("/embeddings")
    hits = search(client, "poison", mode="hybrid", top_k=2)
    assert len(hits) == 2
    assert hits[0]["score"] >= hits[1]["score"]
    scoped = search(client, "poison", mode="hybrid", document_id=doc["id"], top_k=10)
    assert {h["citation"]["document_id"] for h in scoped} == {doc["id"]}


@pytest.mark.integration
def test_default_mode_comes_from_settings_and_is_vector(client, embedder):
    upload(client)
    client.post("/embeddings")
    default = search(client, "poison stack")
    explicit = search(client, "poison stack", mode="vector")
    assert [h["chunk_id"] for h in default] == [h["chunk_id"] for h in explicit]


@pytest.mark.integration
def test_invalid_mode_is_rejected(client, embedder):
    assert client.post("/search", json={"query": "x", "mode": "magic"}).status_code == 422
