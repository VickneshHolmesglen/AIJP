import httpx
import pytest

from app.embeddings import EmbeddingError, OllamaEmbedder


def _embedder(handler: httpx.MockTransport, dim: int = 3) -> OllamaEmbedder:
    client = httpx.Client(base_url="http://ollama", transport=handler)
    return OllamaEmbedder("http://ollama", "m", dim, client=client)


def test_embed_returns_vectors_in_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[1, 0, 0], [0, 1, 0]]})

    assert _embedder(httpx.MockTransport(handler)).embed(["a", "b"]) == [[1, 0, 0], [0, 1, 0]]


def test_embed_empty_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not be called")

    assert _embedder(httpx.MockTransport(handler)).embed([]) == []


def test_wrong_dimension_is_rejected() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"embeddings": [[1, 2]]}))
    with pytest.raises(EmbeddingError, match="2-d vectors"):
        _embedder(transport).embed(["a"])


def test_count_mismatch_is_rejected() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"embeddings": []}))
    with pytest.raises(EmbeddingError, match="Expected 1"):
        _embedder(transport).embed(["a"])


def test_http_error_becomes_embedding_error() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    with pytest.raises(EmbeddingError, match="request failed"):
        _embedder(transport).embed(["a"])


def test_malformed_body_becomes_embedding_error() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"nope": 1}))
    with pytest.raises(EmbeddingError, match="Unexpected response"):
        _embedder(transport).embed(["a"])
