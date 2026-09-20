import pytest

from app.api.search import get_embedder
from app.main import app
from tests.fakes import DownEmbedder, FakeEmbedder

pytestmark = pytest.mark.integration

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


def test_embed_fills_pending_chunks_once(client, embedder):
    upload(client)
    assert client.post("/embeddings").json() == {"embedded": 3}
    assert client.post("/embeddings").json() == {"embedded": 0}


def test_search_ranks_relevant_chunk_first_with_citation(client, embedder):
    doc = upload(client, source_path="design/towers.md").json()
    client.post("/embeddings")

    response = client.post("/search", json={"query": "how does poison stack", "top_k": 2})
    assert response.status_code == 200
    hits = response.json()["hits"]
    assert len(hits) == 2
    top = hits[0]
    assert "Poison stacks" in top["content"]
    assert top["score"] > hits[1]["score"]
    assert top["citation"] == {
        "document_id": doc["id"],
        "source_path": "design/towers.md",
        "section": "Towers > Poison",
        "page": None,
        "start_line": 4,
        "end_line": 5,
    }


def test_search_ignores_unembedded_chunks(client, embedder):
    upload(client)
    assert client.post("/search", json={"query": "poison"}).json()["hits"] == []


def test_search_can_be_scoped_to_one_document(client, embedder):
    upload(client)
    other = upload(client, "other.txt", b"poison is also mentioned here").json()
    client.post("/embeddings")

    hits = client.post("/search", json={"query": "poison", "document_id": other["id"]}).json()[
        "hits"
    ]
    assert hits and {h["citation"]["document_id"] for h in hits} == {other["id"]}


def test_search_validates_input(client, embedder):
    assert client.post("/search", json={"query": ""}).status_code == 422
    assert client.post("/search", json={"query": "x", "top_k": 0}).status_code == 422


def test_provider_outage_returns_503(client):
    app.dependency_overrides[get_embedder] = DownEmbedder
    try:
        upload(client)
        assert client.post("/embeddings").status_code == 503
        assert client.post("/search", json={"query": "poison"}).status_code == 503
    finally:
        app.dependency_overrides.pop(get_embedder, None)
